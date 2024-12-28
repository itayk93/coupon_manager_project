import os
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Company
from app.forms import CompanyManagementForm, DeleteCompanyForm

admin_companies_bp = Blueprint('admin_companies_bp', __name__)

@admin_companies_bp.route('/admin/manage_companies', methods=['GET', 'POST'])
@login_required
def manage_companies():
    if not current_user.is_admin:
        flash('אין לך הרשאה לצפות בעמוד זה.', 'danger')
        return redirect(url_for('index'))

    form = CompanyManagementForm()
    delete_form = DeleteCompanyForm()

    if form.validate_on_submit() and 'submit' in request.form:
        company_name = form.name.data.strip()
        existing_company = Company.query.filter_by(name=company_name).first()
        if existing_company:
            flash('חברה זו כבר קיימת.', 'warning')
            return redirect(url_for('admin_companies_bp.manage_companies'))

        # יצירת חברה חדשה
        new_company = Company(name=company_name)
        db.session.add(new_company)
        db.session.commit()
        flash('חברה חדשה נוספה בהצלחה!', 'success')
        return redirect(url_for('admin_companies_bp.manage_companies'))

    companies = Company.query.order_by(Company.id.asc()).all()
    return render_template('admin/admin_manage_companies.html', form=form, companies=companies, delete_form=delete_form)


@admin_companies_bp.route('/admin/delete_company/<int:company_id>', methods=['POST'])
@login_required
def delete_company(company_id):
    if not current_user.is_admin:
        flash('אין לך הרשאה לביצוע פעולה זו.', 'danger')
        return redirect(url_for('index'))

    try:
        # שליפת החברה ומחיקתה
        company = Company.query.get_or_404(company_id)
        db.session.delete(company)
        db.session.commit()
        flash(f'חברה "{company.name}" נמחקה בהצלחה.', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"Error while deleting company: {e}")
        flash('שגיאה במחיקת החברה.', 'danger')

    return redirect(url_for('admin_companies_bp.manage_companies'))
