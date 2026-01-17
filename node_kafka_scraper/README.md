# Node Kafka Coupon Scraper

This isolated microservice orchestrates Kafka, Selenium, and Supabase to replicate the coupon auto-update workflow currently embedded in the monolith. It lives under `node_kafka_scraper/` and can run independently; the existing app is untouched.

## Architecture

- **Producer (`src/producer.js`)**: invoked by a cron job to fetch eligible coupons from Supabase, create an `auto_update_runs` record, and publish a single batch message to Kafka.
- **Consumer (`src/index.js`)**: long-running Kafka consumer that spills the batch, scrapes each coupon with Selenium, updates Supabase (`coupon`, `coupon_usage`, `auto_update_runs`), and logs per-coupon results.
- **Selenium runner (`src/seleniumRunner.js`)**: builds the WebDriver (local or remote) and extracts usage totals from the coupon landing page.
- **Supabase client (`src/supabaseClient.js`)**: encapsulates all Supabase operations to keep the service isolated.
- **Kafka client (`src/kafkaClient.js`)**: shared logic for connecting a producer or consumer to the configured brokers.

## Getting started

1. Copy `.env.example` to `.env` and populate:
   - `KAFKA_*` for your Kafka cluster.
   - `SUPABASE_*` for the service role credentials.
   - Selenium host details (`SELENIUM_REMOTE_URL`, `SCRAPER_HEADLESS`, timeouts, etc.).
2. Install dependencies: `npm install`.
3. Run the consumer: `npm start`. Keep it running for Kafka to deliver batches.
4. Schedule the producer via cron/Render job:

   ```bash
   0 4 * * * cd "$PROJECT_ROOT/node_kafka_scraper" && npm run produce
   ```

   Ensure the environment variables are available to the cron environment (Source `.env` or export individually).

## Supabase expectations

- `coupon` table: updates `used_value` and `last_scraped`.
- `coupon_usage` table: inserts a row per successful scrape (action `עדכון אוטומטי`).
- `auto_update_runs` table: run status is advanced from `running` -> `queued` -> `success/failed`.

The service only touches rows where `auto_download_details IS NOT NULL`.

## Observability & maintenance

- Logs are emitted through `pino`; send them to a log collector or file via redirect.
- Retry Kafka delivery by relying on Kafka's at-least-once semantics; the consumer handles failures without crashing (job-level errors are logged but not rethrown to avoid duplicates).
- Selenium errors propagate to Supabase via `auto_update_runs` (status `failed` and error message).

## Testing & validation

- Run the producer locally against a test Supabase project and Kafka cluster.
- Start a consumer instance and ensure `coupon_usage` rows appear with accurate totals.
- Validate `auto_update_runs` entries match the run lifecycle; inspect `job_id` if needed.
