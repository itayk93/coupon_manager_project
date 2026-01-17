const { connectConsumer } = require('./kafkaClient');
const {
  updateCouponRecord,
  insertCouponUsage,
  updateRunStatus
} = require('./supabaseClient');
const { runScrapeForCoupon } = require('./seleniumRunner');
const logger = require('./logger');

const TOPIC = process.env.KAFKA_TOPIC || 'coupon-auto-updates';
const CONCURRENCY = parseInt(process.env.CONSUMER_CONCURRENCY || '1', 10);

async function processCoupon(coupon) {
  const startTime = Date.now();
  const scrapeResult = await runScrapeForCoupon(coupon);

  if (!scrapeResult.success) {
    throw new Error(scrapeResult.error || 'Scrape returned failure');
  }

  const usagesPayload = {
    couponId: coupon.id,
    usedAmount: scrapeResult.usedAmount,
    action: 'עדכון אוטומטי',
    details: `Node scraper updated usage: ${scrapeResult.message || 'n/a'}`
  };

  await updateCouponRecord(coupon.id, {
    used_value: scrapeResult.usedAmount,
    last_scraped: new Date().toISOString()
  });

  await insertCouponUsage(
    usagesPayload.couponId,
    usagesPayload.usedAmount,
    usagesPayload.action,
    usagesPayload.details
  );

  const duration = Date.now() - startTime;
  logger.info(
    { coupon: coupon.id, duration, usedAmount: scrapeResult.usedAmount },
    'Coupon update persisted'
  );

  return {
    couponId: coupon.id,
    status: 'success'
  };
}

async function handleJob(messageValue) {
  const payload = JSON.parse(messageValue);
  const runId = payload.runId;
  const coupons = payload.coupons || [];

  await updateRunStatus(runId, {
    status: 'running',
    message: `Processing ${coupons.length} coupons`
  });

  const result = {
    processed: 0,
    success: 0,
    failed: 0,
    failures: []
  };

  for (const coupon of coupons) {
    result.processed += 1;
    try {
      await processCoupon(coupon);
      result.success += 1;
    } catch (error) {
      result.failed += 1;
      result.failures.push({
        couponId: coupon.id,
        error: error.message
      });
      logger.error({ coupon: coupon.id, error: error.message }, 'Coupon processing failed');
    }
  }

  const finalStatus = result.failed ? 'failed' : 'success';
  await updateRunStatus(runId, {
    status: finalStatus,
    message: `Processed ${result.processed} coupons (success: ${result.success}, failed: ${result.failed})`,
    updated_count: result.success,
    failed_count: result.failed
  });

  logger.info(
    { runId, result },
    'Job completed'
  );
}

async function run() {
  const consumer = await connectConsumer(TOPIC);

  await consumer.run({
    partitionsConsumedConcurrently: CONCURRENCY,
    eachMessage: async ({ message }) => {
      const text = message.value.toString();
      logger.info({ offset: message.offset }, 'Received Kafka job');
      try {
        await handleJob(text);
      } catch (error) {
        logger.error({ error: error.message }, 'Failed processing Kafka job');
      }
    }
  });
}

run().catch((err) => {
  logger.error({ err: err.message }, 'Consumer crashed');
  process.exit(1);
});
