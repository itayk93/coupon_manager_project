const { createClient } = require('@supabase/supabase-js');
const logger = require('./logger');

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!supabaseUrl || !supabaseKey) {
  throw new Error('SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required');
}

const supabase = createClient(supabaseUrl, supabaseKey);

async function fetchAutoUpdateCoupons(limit = 200) {
  const { data, error } = await supabase
    .from('coupon')
    .select('id, code, company, user_id, auto_download_details')
    .eq('status', 'פעיל')
    .eq('is_one_time', false)
    .eq('is_available', true)
    .eq('auto_update', true)
    .not('auto_download_details', 'is', null)
    .limit(limit);

  if (error) {
    logger.error({ error }, 'Failed to fetch auto-update coupons from Supabase');
    throw error;
  }

  return data || [];
}

async function updateCouponRecord(couponId, payload) {
  const { error } = await supabase
    .from('coupon')
    .update(payload)
    .eq('id', couponId);

  if (error) {
    logger.error({ couponId, error }, 'Failed to update coupon record');
    throw error;
  }
}

async function insertCouponUsage(couponId, usedAmount, action, details) {
  const { error } = await supabase.from('coupon_usage').insert({
    coupon_id: couponId,
    used_amount: usedAmount,
    action,
    details,
    timestamp: new Date().toISOString()
  }).limit(1);

  if (error) {
    logger.error({ couponId, error }, 'Failed to insert coupon usage record');
    throw error;
  }
}

async function createAutoUpdateRun({ triggeredByUserId = null, runType = 'cron', message = '' } = {}) {
  const { data, error } = await supabase
    .from('auto_update_runs')
    .insert({
      triggered_by_user_id: triggeredByUserId,
      run_type: runType,
      status: 'running',
      message
    })
    .select('id')
    .single();

  if (error) {
    logger.error({ error }, 'Failed to create auto update run record');
    throw error;
  }

  return data;
}

async function updateRunStatus(runId, updates = {}) {
  const { error } = await supabase
    .from('auto_update_runs')
    .update({
      ...updates,
      finished_at: updates.finished_at || new Date().toISOString()
    })
    .eq('id', runId)
    .limit(1);

  if (error) {
    logger.error({ runId, error }, 'Failed to update auto update run status');
    throw error;
  }
}

module.exports = {
  fetchAutoUpdateCoupons,
  updateCouponRecord,
  insertCouponUsage,
  createAutoUpdateRun,
  updateRunStatus
};
