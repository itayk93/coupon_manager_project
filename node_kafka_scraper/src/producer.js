const { connectProducer } = require('./kafkaClient');
const {
  fetchAutoUpdateCoupons,
  createAutoUpdateRun,
  updateRunStatus
} = require('./supabaseClient');
const logger = require('./logger');

const TOPIC = process.env.KAFKA_TOPIC || 'coupon-auto-updates';
const LIMIT = parseInt(process.env.CRON_FETCH_LIMIT || '250', 10);

async function main() {
  logger.info('Starting auto-update producer job');
  const coupons = await fetchAutoUpdateCoupons(LIMIT);

  if (!coupons.length) {
    logger.info('No coupons eligible for auto-update');
    return;
  }

  const run = await createAutoUpdateRun({
    runType: 'cron',
    message: `Enqueue ${coupons.length} auto-update coupons`
  });

  const producer = await connectProducer();
  const payload = {
    runId: run.id,
    coupons
  };

  await producer.send({
    topic: TOPIC,
    messages: [
      {
        value: JSON.stringify(payload),
        key: `run-${run.id}`
      }
    ]
  });

  await updateRunStatus(run.id, {
    status: 'queued',
    message: `Produced ${coupons.length} coupons for Kafka`,
    job_id: `run-${run.id}`
  });

  logger.info({ runId: run.id, count: coupons.length }, 'Job enqueued');
  await producer.disconnect();
}

main().catch((error) => {
  logger.error({ error }, 'Producer job failed');
  process.exit(1);
});
