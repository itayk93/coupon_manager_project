# app/routes/sharing_routes.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, timezone, timedelta
import secrets
import uuid
from app.extensions import db
from app.models import (
    Coupon,
    CouponShares,
    CouponActiveViewers,
    User,
    Notification,
    Company
)
from app.helpers import send_email

sharing_bp = Blueprint("sharing", __name__)


@sharing_bp.route("/generate_share_link/<int:coupon_id>", methods=["POST"])
@login_required
def generate_share_link(coupon_id):
    """Generate a secure link for coupon sharing"""
    try:
        # Find the coupon
        coupon = Coupon.query.get_or_404(coupon_id)
        
        # Verify user is the original owner
        if coupon.user_id != current_user.id:
            flash("אין לך הרשאה לשתף קופון זה", "error")
            return redirect(url_for('coupons.coupon_detail', id=coupon_id))
        
        # Verify coupon is active
        if coupon.status != "פעיל":
            flash("לא ניתן לשתף קופון לא פעיל", "error")
            return redirect(url_for('coupons.coupon_detail', id=coupon_id))
        
        # Generate unique secure token
        share_token = secrets.token_urlsafe(32)
        
        # Create share record
        share = CouponShares(
            coupon_id=coupon_id,
            shared_by_user_id=current_user.id,
            share_token=share_token,
            status="pending",
            share_expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        
        db.session.add(share)
        db.session.commit()
        
        # Generate the share link
        share_link = url_for('sharing.share_coupon', token=share_token, _external=True)
        
        return jsonify({
            "success": True,
            "share_link": share_link,
            "expires_at": share.share_expires_at.isoformat()
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error generating share link: {str(e)}", exc_info=True)
        return jsonify({"success": False, "error": "An error occurred. Please try again."}), 500


@sharing_bp.route("/get_current_share_link/<int:coupon_id>", methods=["GET"])
@login_required
def get_current_share_link(coupon_id):
    """Get the current active share link status"""
    try:
        coupon = Coupon.query.get_or_404(coupon_id)
        
        if coupon.user_id != current_user.id:
            return jsonify({"success": False, "error": "Unauthorized"}), 403
        
        # Check for pending share link
        current_share = CouponShares.query.filter_by(
            coupon_id=coupon_id,
            shared_by_user_id=current_user.id,
            status="pending"
        ).order_by(CouponShares.created_at.desc()).first()
        
        if not current_share:
            return jsonify({"status": "none"})
        
        # Check if expired
        if current_share.share_expires_at < datetime.now(timezone.utc):
            current_share.status = "expired"
            db.session.commit()
            return jsonify({"status": "expired"})
        
        # Active link
        share_link = url_for('sharing.share_coupon', token=current_share.share_token, _external=True)
        return jsonify({
            "status": "active",
            "link": share_link,
            "expires_at": current_share.share_expires_at.isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting current share link: {str(e)}", exc_info=True)
        return jsonify({"success": False, "error": "An error occurred"}), 500


@sharing_bp.route("/share_coupon/<token>", methods=["GET"])
@login_required
def share_coupon(token):
    """Coupon sharing confirmation page"""
    try:
        # Find share record
        share = CouponShares.query.filter_by(share_token=token).first()
        
        if not share:
            return render_template("share_expired.html", 
                                 message="Invalid or expired share link")
        
        # Check if expired
        if share.share_expires_at < datetime.now(timezone.utc):
            share.status = "expired"
            db.session.commit()
            return render_template("share_expired.html", 
                                 message="This share link has expired")
        
        # Check if already used
        if share.status != "pending":
            return render_template("share_expired.html", 
                                 message="קישור זה כבר נוצל")
        
        # Get coupon and sharing user details
        coupon = share.coupon
        sharing_user = share.shared_by_user
        
        # Get company logo
        companies = Company.query.order_by(Company.name).all()
        company_logo_mapping = {c.name.lower(): c.image_path for c in companies}
        for company_name in company_logo_mapping:
            if not company_logo_mapping[company_name]:
                company_logo_mapping[company_name] = "images/default.png"
        
        company_logo = company_logo_mapping.get(
            coupon.company.lower(), "images/default_logo.png"
        )
        
        return render_template("share_confirmation.html",
                             coupon=coupon,
                             sharing_user=sharing_user,
                             share_token=token,
                             company_logo=company_logo)
        
    except Exception as e:
        current_app.logger.error(f"Error in share_coupon: {str(e)}", exc_info=True)
        flash("אירעה שגיאה בעיבוד קישור השיתוף", "error")
        return redirect(url_for('coupons.show_coupons'))


@sharing_bp.route("/confirm_share/<token>", methods=["POST"])
@login_required
def confirm_share(token):
    """Confirm coupon sharing"""
    try:
        # Find share record
        share = CouponShares.query.filter_by(share_token=token).first()
        
        if not share or share.status != "pending":
            flash("קישור שיתוף לא תקין או פג תוקף", "error")
            return redirect(url_for('coupons.show_coupons'))
        
        # Check if expired
        if share.share_expires_at < datetime.now(timezone.utc):
            share.status = "expired"
            db.session.commit()
            flash("קישור השיתוף פג תוקף", "error")
            return redirect(url_for('coupons.show_coupons'))
        
        # Update share record
        share.status = "accepted"
        share.shared_with_user_id = current_user.id
        share.accepted_at = datetime.now(timezone.utc)
        
        # Generate revocation token (15 minute expiry)
        share.revocation_token = secrets.token_urlsafe(32)
        share.revocation_token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        
        # Create notifications
        # For sharing user
        notification_sharing = Notification(
            user_id=share.shared_by_user_id,
            message=f"{current_user.first_name} {current_user.last_name} קיבל גישה לקופון שלך",
            link=url_for('coupons.coupon_detail', id=share.coupon_id)
        )
        
        # For accepting user
        notification_accepting = Notification(
            user_id=current_user.id,
            message=f"קיבלת גישה לקופון {share.coupon.company}",
            link=url_for('coupons.coupon_detail', id=share.coupon_id)
        )
        
        db.session.add_all([notification_sharing, notification_accepting])
        db.session.commit()
        
        # Send email to sharing user with revocation option
        try:
            from flask import render_template
            revocation_link = url_for('sharing.quick_revoke', token=share.revocation_token, _external=True)
            html_content = render_template(
                "emails/coupon_sharing_accepted.html",
                user=share.shared_by_user,
                accepting_user=current_user,
                coupon=share.coupon,
                revocation_link=revocation_link
            )
            send_email(
                sender_email="noreply@couponmasteril.com",
                sender_name="Coupon Master",
                recipient_email=share.shared_by_user.email,
                recipient_name=f"{share.shared_by_user.first_name} {share.shared_by_user.last_name}",
                subject="שיתוף הקופון אושר",
                html_content=html_content
            )
        except Exception as e:
            current_app.logger.error(f"Error sending sharing acceptance email: {str(e)}")
        
        flash("שיתוף הקופון אושר בהצלחה!", "success")
        return redirect(url_for('coupons.coupon_detail', id=share.coupon_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error confirming share: {str(e)}", exc_info=True)
        flash("אירעה שגיאה. אנא נסה שוב.", "error")
        return redirect(url_for('coupons.show_coupons'))


@sharing_bp.route("/revoke_sharing/<int:share_id>", methods=["POST"])
@login_required
def revoke_sharing(share_id):
    """Revoke coupon sharing"""
    try:
        share = CouponShares.query.get_or_404(share_id)
        
        # Verify user is authorized to revoke
        if share.shared_by_user_id != current_user.id and share.shared_with_user_id != current_user.id:
            return jsonify({"success": False, "error": "Unauthorized"}), 403
        
        # Verify share is accepted
        if share.status != "accepted":
            return jsonify({"success": False, "error": "Share is not active"}), 400
        
        # Update share record
        share.status = "revoked"
        share.revoked_at = datetime.now(timezone.utc)
        
        # Create notifications for both users
        other_user_id = share.shared_with_user_id if current_user.id == share.shared_by_user_id else share.shared_by_user_id
        
        notification_current = Notification(
            user_id=current_user.id,
            message=f"ביטלת את הגישה לקופון {share.coupon.company}",
            link=url_for('coupons.coupon_detail', id=share.coupon_id)
        )
        
        notification_other = Notification(
            user_id=other_user_id,
            message=f"הגישה לקופון {share.coupon.company} בוטלה",
            link=url_for('coupons.show_coupons')
        )
        
        db.session.add_all([notification_current, notification_other])
        db.session.commit()
        
        # Send email notifications
        try:
            from flask import render_template
            other_user = User.query.get(other_user_id)
            html_content = render_template(
                "emails/coupon_sharing_revoked.html",
                user=other_user,
                coupon=share.coupon,
                revoked_by=current_user
            )
            send_email(
                sender_email="noreply@couponmasteril.com",
                sender_name="Coupon Master",
                recipient_email=other_user.email,
                recipient_name=f"{other_user.first_name} {other_user.last_name}",
                subject="שיתוף הקופון בוטל",
                html_content=html_content
            )
        except Exception as e:
            current_app.logger.error(f"Error sending revocation email: {str(e)}")
        
        return jsonify({"success": True, "message": "Sharing revoked successfully"})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error revoking sharing: {str(e)}", exc_info=True)
        return jsonify({"success": False, "error": "An error occurred"}), 500


@sharing_bp.route("/quick_revoke/<token>", methods=["GET"])
def quick_revoke(token):
    """Quick revocation from email (15-minute window)"""
    try:
        # Find share record by revocation token
        share = CouponShares.query.filter_by(revocation_token=token).first()
        
        if not share:
            return render_template("share_expired.html", 
                                 message="Invalid revocation link")
        
        # Check if revocation token expired
        if share.revocation_token_expires_at < datetime.now(timezone.utc):
            return render_template("share_expired.html", 
                                 message="Revocation link has expired")
        
        # Check if share is still active
        if share.status != "accepted":
            return render_template("share_expired.html", 
                                 message="This coupon is no longer shared")
        
        # Revoke the sharing
        share.status = "revoked"
        share.revoked_at = datetime.now(timezone.utc)
        
        # Create notifications
        notification_owner = Notification(
            user_id=share.shared_by_user_id,
            message=f"ביטלת את הגישה לקופון {share.coupon.company}",
            link=url_for('coupons.coupon_detail', id=share.coupon_id)
        )
        
        notification_recipient = Notification(
            user_id=share.shared_with_user_id,
            message=f"הגישה לקופון {share.coupon.company} בוטלה",
            link=url_for('coupons.show_coupons')
        )
        
        db.session.add_all([notification_owner, notification_recipient])
        db.session.commit()
        
        # Send confirmation email to recipient
        try:
            from flask import render_template
            html_content = render_template(
                "emails/coupon_sharing_revoked.html",
                user=share.shared_with_user,
                coupon=share.coupon,
                revoked_by=share.shared_by_user
            )
            send_email(
                sender_email="noreply@couponmasteril.com",
                sender_name="Coupon Master",
                recipient_email=share.shared_with_user.email,
                recipient_name=f"{share.shared_with_user.first_name} {share.shared_with_user.last_name}",
                subject="שיתוף הקופון בוטל",
                html_content=html_content
            )
        except Exception as e:
            current_app.logger.error(f"Error sending revocation confirmation email: {str(e)}")
        
        return render_template("share_success.html", 
                             message="Coupon sharing has been revoked successfully")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in quick_revoke: {str(e)}", exc_info=True)
        return render_template("share_expired.html", 
                             message="An error occurred processing your request")


@sharing_bp.route("/track_coupon_viewer/<int:coupon_id>", methods=["POST"])
@login_required
def track_coupon_viewer(coupon_id):
    """Track user viewing coupon details"""
    try:
        # Generate or get session ID
        session_id = request.json.get('session_id') or str(uuid.uuid4())
        
        # Create or update viewer record
        viewer = CouponActiveViewers.query.filter_by(
            coupon_id=coupon_id,
            user_id=current_user.id,
            session_id=session_id
        ).first()
        
        if viewer:
            viewer.last_activity = datetime.now(timezone.utc)
        else:
            viewer = CouponActiveViewers(
                coupon_id=coupon_id,
                user_id=current_user.id,
                session_id=session_id,
                last_activity=datetime.now(timezone.utc)
            )
            db.session.add(viewer)
        
        # Clean up old records (older than 5 minutes)
        old_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
        CouponActiveViewers.query.filter(
            CouponActiveViewers.last_activity < old_threshold
        ).delete()
        
        # Get other active viewers
        other_viewers = CouponActiveViewers.query.filter(
            CouponActiveViewers.coupon_id == coupon_id,
            CouponActiveViewers.user_id != current_user.id,
            CouponActiveViewers.last_activity > old_threshold
        ).all()
        
        other_viewers_data = []
        for viewer in other_viewers:
            other_viewers_data.append({
                'user_id': viewer.user_id,
                'first_name': viewer.user.first_name,
                'last_name': viewer.user.last_name
            })
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "session_id": session_id,
            "other_viewers": other_viewers_data
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error tracking coupon viewer: {str(e)}", exc_info=True)
        return jsonify({"success": False, "error": "An error occurred"}), 500


@sharing_bp.route("/get_active_viewers/<int:coupon_id>", methods=["GET"])
@login_required
def get_active_viewers(coupon_id):
    """Get list of users currently viewing coupon"""
    try:
        # Clean up old records
        old_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
        CouponActiveViewers.query.filter(
            CouponActiveViewers.last_activity < old_threshold
        ).delete()
        
        # Get active viewers excluding current user
        active_viewers = CouponActiveViewers.query.filter(
            CouponActiveViewers.coupon_id == coupon_id,
            CouponActiveViewers.user_id != current_user.id,
            CouponActiveViewers.last_activity > old_threshold
        ).all()
        
        viewers_data = []
        for viewer in active_viewers:
            viewers_data.append({
                'user_id': viewer.user_id,
                'first_name': viewer.user.first_name,
                'last_name': viewer.user.last_name,
                'last_activity': viewer.last_activity.isoformat()
            })
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "active_viewers": viewers_data
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error getting active viewers: {str(e)}", exc_info=True)
        return jsonify({"success": False, "error": "An error occurred"}), 500