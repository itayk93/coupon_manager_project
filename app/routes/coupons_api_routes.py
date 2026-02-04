import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from flask import current_app, flash, jsonify, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.sql import text

from app.extensions import csrf, db
from app.helpers import extract_coupon_detail_sms, should_update_coupon, update_coupon_status
from app.models import (
    Company,
    Coupon,
    CouponShares,
    CouponTransaction,
    CouponUsage,
    User,
    UserTourProgress,
)
from app.routes.coupons_routes import coupons_bp
from app.tasks import dispatch_multipass_github_workflow, trigger_multipass_github_action

logger = logging.getLogger(__name__)


@coupons_bp.route(
    "/delete_transaction_record/<string:source_table>/<int:record_id>", methods=["POST"]
)
@login_required
def delete_transaction_record(source_table, record_id):
    user_id = current_user.id

    if source_table == "coupon_usage":
        usage = CouponUsage.query.get_or_404(record_id)
        coupon = usage.coupon
        if coupon.user_id != user_id:
            flash("אין לך הרשאה למחוק שימוש זה.", "danger")
            return redirect(url_for("coupons.coupon_detail", id=coupon.id))

        coupon.used_value -= usage.used_amount
        if coupon.used_value < 0:
            coupon.used_value = 0

        db.session.delete(usage)
        update_coupon_status(coupon)

    elif source_table == "coupon_transaction":
        transaction = CouponTransaction.query.get_or_404(record_id)
        coupon = Coupon.query.get(transaction.coupon_id)
        if not coupon or coupon.user_id != user_id:
            flash("אין לך הרשאה למחוק טעינה זו.", "danger")
            return redirect(
                url_for("coupons.coupon_detail", id=coupon.id if coupon else None)
            )

        # --- Prevent deleting Multipass transactions (Security) ---
        # Allow owner or admin to delete
        pass

        # --- ❌ מניעת מחיקת הרשומה הראשונית ---
        if transaction.reference_number in ["ManualEntry", "Initial"]:
            flash("לא ניתן למחוק את הטעינה הראשונית של הקופון.", "danger")
            return redirect(url_for("coupons.coupon_detail", id=coupon.id))

        # אחרת, זו טעינה/שימוש רגילה – אפשר להמשיך בלוגיקה הרגילה:
        if transaction.recharge_amount > 0:
            new_value = coupon.value - transaction.recharge_amount
            if new_value < coupon.used_value:
                flash("לא ניתן למחוק טעינה שכבר נוצלה בחלקה.", "danger")
                return redirect(url_for("coupons.coupon_detail", id=coupon.id))
            coupon.value = new_value

        if transaction.usage_amount > 0:
            coupon.used_value -= transaction.usage_amount
            if coupon.used_value < 0:
                coupon.used_value = 0

        db.session.delete(transaction)
        update_coupon_status(coupon)

    else:
        flash("טבלה לא מוכרת, לא ניתן למחוק.", "danger")
        return redirect(url_for("coupons.show_coupons"))

    try:
        db.session.commit()
        flash("הרשומה נמחקה בהצלחה.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting transaction record: {e}")
        flash("שגיאה בעת מחיקת הרשומה.", "danger")

    return redirect(url_for("coupons.coupon_detail", id=coupon.id))


@coupons_bp.route("/update_company_view", methods=["POST"])
@login_required
def update_company_view():
    """Update last_company_view timestamp for all coupons of a specific company."""
    try:
        data = request.get_json()
        company = data.get("company")

        logger.info(
            "update_company_view called for user %s, company: %s",
            current_user.id,
            company,
        )

        if not company:
            logger.warning("No company provided in request")
            return jsonify({"success": False, "error": "Company name is required"})

        user_coupons = Coupon.query.filter_by(
            user_id=current_user.id,
            company=company,
        ).all()

        logger.info("Found %s coupons for company %s", len(user_coupons), company)

        current_time = datetime.now(timezone.utc)

        for coupon in user_coupons:
            coupon.last_company_view = current_time
            logger.debug("Updated coupon %s last_company_view", coupon.id)

        db.session.commit()
        logger.info("Successfully updated %s coupons", len(user_coupons))

        return jsonify({"success": True, "updated_count": len(user_coupons)})
    except Exception as e:
        logger.error("Error in update_company_view: %s", str(e))
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)})


@coupons_bp.route("/update_code_view", methods=["POST"])
@login_required
def update_code_view():
    """Update last_code_view timestamp for a specific coupon."""
    try:
        data = request.get_json()
        coupon_id = data.get("coupon_id")

        if not coupon_id:
            return jsonify({"success": False, "error": "Coupon ID is required"})

        coupon = Coupon.query.filter_by(
            id=coupon_id,
            user_id=current_user.id,
        ).first()

        if not coupon:
            return jsonify({"success": False, "error": "Coupon not found or access denied"})

        coupon.last_code_view = datetime.now(timezone.utc)
        db.session.commit()

        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)})


@coupons_bp.route("/update_coupon_detail_timestamp", methods=["POST"])
@login_required
def update_coupon_detail_timestamp():
    try:
        tour_progress = UserTourProgress.query.filter_by(user_id=current_user.id).first()

        if tour_progress:
            tour_progress.coupon_detail_timestamp = datetime.utcnow()
            db.session.commit()
            return jsonify({"success": True}), 200
        else:
            return jsonify({"error": "Tour progress record not found"}), 404

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@coupons_bp.route("/update_tour_progress", methods=["POST"])
@login_required
def update_tour_progress():
    try:
        tour_progress = UserTourProgress.query.filter_by(user_id=current_user.id).first()
        if not tour_progress:
            tour_progress = UserTourProgress(user_id=current_user.id)
            db.session.add(tour_progress)

        tour_type = request.form.get("tour_type", "add_coupon")
        if tour_type == "add_coupon":
            tour_progress.add_coupon_timestamp = (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .strftime("%Y-%m-%d %H:%M:%S")
            )
        elif tour_type == "coupon_detail":
            tour_progress.coupon_detail_timestamp = (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .strftime("%Y-%m-%d %H:%M:%S")
            )

        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        print(f"Error updating tour progress: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@coupons_bp.route("/api/my_coupons", methods=["GET"])
@login_required
def get_my_coupons():
    """
    API endpoint to get the first 3 coupons for the currently logged-in user.
    """
    try:
        user_id = current_user.id

        coupons = Coupon.query.filter_by(user_id=user_id).limit(3).all()

        coupons_data = []
        for coupon in coupons:
            expiration_date = None
            if coupon.expiration:
                if isinstance(coupon.expiration, str):
                    expiration_date = coupon.expiration
                else:
                    expiration_date = coupon.expiration.isoformat()

            date_added = None
            if coupon.date_added:
                if isinstance(coupon.date_added, str):
                    date_added = coupon.date_added
                else:
                    date_added = coupon.date_added.isoformat()

            coupon_dict = {
                "id": coupon.id,
                "code": coupon.code,
                "description": coupon.description,
                "value": coupon.value,
                "cost": coupon.cost,
                "company": coupon.company,
                "expiration": expiration_date,
                "status": coupon.status,
                "is_available": coupon.is_available,
                "is_for_sale": coupon.is_for_sale,
                "date_added": date_added,
            }
            coupons_data.append(coupon_dict)

        return jsonify({"success": True, "coupons": coupons_data})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@coupons_bp.route("/api/process_coupon_text", methods=["POST"])
def process_coupon_text():
    try:
        data = request.get_json()
        text = data.get("text", "")
        companies_list = data.get("companies_list", [])

        extracted_data_df, pricing_df = extract_coupon_detail_sms(text, companies_list)

        if not extracted_data_df.empty:
            extracted_data = extracted_data_df.iloc[0].to_dict()

            for key, value in extracted_data.items():
                if pd.isna(value):
                    extracted_data[key] = None
                elif isinstance(value, np.int64):
                    extracted_data[key] = int(value)
                elif isinstance(value, np.float64):
                    extracted_data[key] = float(value)

            return jsonify({"success": True, "extracted_data": extracted_data})
        else:
            return jsonify({"success": False, "error": "לא ניתן לזהות נתונים בטקסט"})

    except Exception as e:
        logger.error(f"Error in process_coupon_text: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@coupons_bp.route("/api/coupon_detail/<int:coupon_id>", methods=["GET"])
def api_coupon_detail(coupon_id):
    """
    API endpoint that returns coupon detail data with consolidated transaction rows
    exactly like the web version's coupon_detail route
    """
    try:
        user_id = request.headers.get("X-User-ID")
        if not user_id:
            return jsonify({"error": "User authentication required"}), 401

        user_id = int(user_id)
        current_user = User.query.get(user_id)
        if not current_user:
            return jsonify({"error": "Invalid user"}), 401

        coupon = Coupon.query.get_or_404(coupon_id)

        is_owner = coupon.user_id == current_user.id

        has_shared_access = False
        if not is_owner:
            shared_access = CouponShares.query.filter_by(
                coupon_id=coupon_id,
                shared_with_user_id=current_user.id,
                status="accepted",
            ).first()
            has_shared_access = shared_access is not None

        if not (is_owner or has_shared_access):
            return jsonify({"error": "Access denied"}), 403

        coupon.last_detail_view = datetime.now(timezone.utc)
        db.session.commit()

        sql = text(
            """
            WITH CouponFilter AS (
                SELECT DISTINCT coupon_id
                FROM coupon_transaction
                WHERE source = 'Multipass'
            ),
            CombinedData AS (
                SELECT
                    'coupon_usage' AS source_table,
                    id,
                    coupon_id,
                    -used_amount AS transaction_amount,
                    timestamp,
                    action,
                    details,
                    NULL  AS location,
                    0     AS recharge_amount,
                    NULL  AS reference_number,
                    NULL  AS source
                FROM coupon_usage
                WHERE details NOT LIKE '%Multipass%'

                UNION ALL

                SELECT
                    'coupon_transaction' AS source_table,
                    id,
                    coupon_id,
                    -usage_amount + recharge_amount AS transaction_amount,
                    transaction_date AS timestamp,
                    source AS action,
                    CASE WHEN location IS NOT NULL AND location <> ''
                         THEN location ELSE NULL END AS details,
                    location,
                    recharge_amount,
                    reference_number,
                    source
                FROM coupon_transaction
            ),
            SummedData AS (
                SELECT
                    source_table, id, coupon_id, timestamp,
                    transaction_amount, details, action
                FROM CombinedData
                WHERE coupon_id = :coupon_id
                  AND (
                      coupon_id NOT IN (SELECT coupon_id FROM CouponFilter)
                      OR (source_table = 'coupon_transaction' AND action = 'Multipass')
                  )

                UNION ALL

                SELECT
                    'sum_row'        AS source_table,
                    NULL             AS id,
                    coupon_id,
                    NULL             AS timestamp,
                    SUM(transaction_amount) AS transaction_amount,
                    'יתרה בקופון'   AS details,
                    NULL             AS action
                FROM CombinedData
                WHERE coupon_id = :coupon_id
                  AND (
                      coupon_id NOT IN (SELECT coupon_id FROM CouponFilter)
                      OR (source_table = 'coupon_transaction' AND action = 'Multipass')
                  )
                GROUP BY coupon_id
            )
            SELECT source_table, id, coupon_id, timestamp,
                   transaction_amount, details, action
            FROM   SummedData
            ORDER  BY CASE WHEN timestamp IS NULL THEN 1 ELSE 0 END,
                     timestamp ASC;
        """
        )

        result = db.session.execute(sql, {"coupon_id": coupon.id})
        consolidated_rows = result.fetchall()

        transaction_rows = []
        for row in consolidated_rows:
            transaction_rows.append(
                {
                    "source_table": row.source_table,
                    "id": row.id,
                    "coupon_id": row.coupon_id,
                    "transaction_timestamp": row.timestamp.isoformat()
                    if row.timestamp
                    else None,
                    "transaction_amount": float(row.transaction_amount)
                    if row.transaction_amount
                    else 0,
                    "details": row.details,
                    "action": row.action,
                }
            )

        discount_percentage = None
        if coupon.is_for_sale and coupon.value > 0:
            discount_percentage = round(
                ((coupon.value - coupon.cost) / coupon.value) * 100, 2
            )

        companies = Company.query.order_by(Company.name).all()
        company_logo_mapping = {c.name.lower(): c.image_path for c in companies}
        company_logo = company_logo_mapping.get(
            coupon.company.lower(), "images/default_logo.png"
        )

        coupon_data = {
            "id": coupon.id,
            "code": coupon.code,
            "description": coupon.description,
            "value": float(coupon.value),
            "cost": float(coupon.cost),
            "company": coupon.company,
            "expiration": coupon.expiration,
            "source": coupon.source,
            "buyme_coupon_url": coupon.buyme_coupon_url,
            "strauss_coupon_url": coupon.strauss_coupon_url,
            "xgiftcard_coupon_url": coupon.xgiftcard_coupon_url,
            "xtra_coupon_url": coupon.xtra_coupon_url,
            "date_added": coupon.date_added.isoformat(),
            "used_value": float(coupon.used_value) if coupon.used_value else 0,
            "status": coupon.status,
            "is_available": coupon.is_available,
            "is_for_sale": coupon.is_for_sale,
            "is_one_time": coupon.is_one_time,
            "purpose": coupon.purpose,
            "exclude_saving": coupon.exclude_saving,
            "auto_download_details": coupon.auto_download_details,
            "user_id": coupon.user_id,
            "cvv": coupon.cvv,
            "card_exp": coupon.card_exp,
            "show_in_widget": getattr(coupon, "show_in_widget", False),
        }

        response_data = {
            "success": True,
            "coupon": coupon_data,
            "is_owner": is_owner,
            "consolidated_rows": transaction_rows,
            "discount_percentage": discount_percentage,
            "company_logo": company_logo,
            "show_multipass_button": coupon.auto_download_details is not None,
            "can_share": is_owner and coupon.status == "פעיל",
        }

        return jsonify(response_data)

    except Exception as e:
        current_app.logger.error(f"Error in api_coupon_detail: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@coupons_bp.route("/api/cron/update_multipass", methods=["POST"])
@csrf.exempt
def api_update_multipass():
    """
    API endpoint for Cron Jobs to trigger Multipass updates.
    Protected by CRON_SECRET.
    Forces update for User ID 1.
    """
    expected_secret = current_app.config.get("CRON_API_TOKEN")

    if not expected_secret or expected_secret == "your-secure-api-token-here":
        import os

        expected_secret = os.getenv("CRON_SECRET")

    if not expected_secret:
        return jsonify({"error": "CRON_API_TOKEN not configured on server"}), 500

    request_secret = request.headers.get("X-Cron-Secret")
    if request_secret != expected_secret:
        return jsonify({"error": "Unauthorized"}), 401

    target_user_id = 1

    active_multipass_coupons = Coupon.query.filter(
        Coupon.status == "פעיל",
        Coupon.auto_download_details == "Multipass",
        Coupon.user_id == target_user_id,
    ).all()

    if not active_multipass_coupons:
        return (
            jsonify({"message": "No active Multipass coupons found for User ID 1"}),
            200,
        )

    coupons_to_update = [
        c.code for c in active_multipass_coupons if should_update_coupon(c)
    ]

    if not coupons_to_update:
        return (
            jsonify(
                {"message": "All coupons correspond to recent data (filtered by smart logic)"}
            ),
            200,
        )

    mode = request.args.get("mode", "full").strip().lower()

    if mode == "full":
        import threading

        def run_update_thread(codes):
            try:
                print(
                    f"=== [CRON] Starting background thread for {len(codes)} coupons (full) ===",
                    flush=True,
                )
                trigger_multipass_github_action(codes)
            except Exception as e:
                print(f"=== [CRON] Error in background thread: {e} ===", flush=True)

        thread = threading.Thread(target=run_update_thread, args=(coupons_to_update,))
        thread.daemon = True
        thread.start()

        return (
            jsonify(
                {
                    "status": "success",
                    "mode": "full",
                    "message": f"Started full update for {len(coupons_to_update)} coupons",
                    "codes": coupons_to_update,
                }
            ),
            200,
        )

    dispatch_result = dispatch_multipass_github_workflow(coupons_to_update)

    if not dispatch_result.get("success"):
        return (
            jsonify(
                {
                    "status": "error",
                    "mode": "dispatch",
                    "message": "Failed to dispatch GitHub Actions workflow",
                    "details": dispatch_result,
                }
            ),
            502,
        )

    return (
        jsonify(
            {
                "status": "success",
                "mode": "dispatch",
                "message": f"Dispatched GitHub Actions workflow for {len(coupons_to_update)} coupons",
                "codes": coupons_to_update,
                "run_id": dispatch_result.get("run_id"),
                "run_url": dispatch_result.get("run_url"),
                "workflow": dispatch_result.get("workflow"),
                "ref": dispatch_result.get("ref"),
            }
        ),
        200,
    )


@coupons_bp.route("/update_single_multipass/<int:id>", methods=["POST"])
@login_required
def update_single_multipass(id):
    """
    Triggers GitHub Action update for a single Multipass coupon.
    """
    coupon = Coupon.query.get_or_404(id)

    if not (current_user.is_admin or coupon.user_id == current_user.id):
        flash("אין לך הרשאה לעדכן קופון זה.", "danger")
        return redirect(url_for("coupons.coupon_detail", id=id))

    if coupon.auto_download_details != "Multipass":
        flash("קופון זה אינו מוגדר כ-Multipass.", "warning")
        return redirect(url_for("coupons.coupon_detail", id=id))

    import threading

    def run_update_thread(codes):
        try:
            print(
                f"=== Starting background thread for single coupon {codes[0]} ===",
                flush=True,
            )
            trigger_multipass_github_action(codes)
        except Exception as e:
            print(f"=== Error in background thread: {e} ===", flush=True)

    thread = threading.Thread(target=run_update_thread, args=([coupon.code],))
    thread.daemon = True
    thread.start()

    flash("תהליך העדכון האוטומטי (GitHub) החל. תקבל מייל בסיום.", "info")
    return redirect(url_for("coupons.coupon_detail", id=id))
