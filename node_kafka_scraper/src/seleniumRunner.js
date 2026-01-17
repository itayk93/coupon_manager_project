const { Builder, until } = require('selenium-webdriver');
const chrome = require('selenium-webdriver/chrome');
const logger = require('./logger');

const SELENIUM_REMOTE_URL = process.env.SELENIUM_REMOTE_URL || null;
const SELENIUM_BROWSER = process.env.SELENIUM_BROWSER || 'chrome';
const HEADLESS = process.env.SCRAPER_HEADLESS !== 'false';
const TIMEOUT_MS = parseInt(process.env.SELENIUM_TIMEOUT || '30000', 10);
const SCRAPER_WAIT_MS = parseInt(process.env.SCRAPER_WAIT_MS || '2000', 10);

async function buildDriver() {
  const options = new chrome.Options();
  if (HEADLESS) options.headless();
  options.addArguments('--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu');
  if (SELENIUM_REMOTE_URL) {
    return new Builder()
      .forBrowser(SELENIUM_BROWSER)
      .usingServer(SELENIUM_REMOTE_URL)
      .setChromeOptions(options)
      .build();
  }

  return new Builder().forBrowser(SELENIUM_BROWSER).setChromeOptions(options).build();
}

async function waitForPageReady(driver) {
  await driver.wait(async () => {
    const readyState = await driver.executeScript('return document.readyState');
    return readyState === 'complete';
  }, TIMEOUT_MS);
}

async function scrapeCouponUsage(driver, coupon) {
  await driver.get(coupon.auto_download_details);
  await waitForPageReady(driver);
  await driver.sleep(SCRAPER_WAIT_MS);

  // Placeholder logic: override with selectors from coupon metadata as needed.
  const usageText = await driver.executeScript(`
    const element = document.querySelector('[data-usage-amount]');
    return element ? element.textContent.trim() : null;
  `);

  if (!usageText) {
    throw new Error('Could not locate usage amount on scraped page');
  }

  const sanitized = usageText.replace(/[^\d\.]/g, '');
  const usedValue = parseFloat(sanitized);
  if (Number.isNaN(usedValue)) {
    throw new Error(`Usage amount is not a number (${usageText})`);
  }

  return {
    usedAmount: usedValue,
    raw: usageText
  };
}

async function runScrapeForCoupon(coupon) {
  const driver = await buildDriver();

  try {
    logger.info({ coupon: coupon.id }, 'Starting Selenium scrape');
    const { usedAmount, raw } = await scrapeCouponUsage(driver, coupon);
    logger.info(
      { coupon: coupon.id, usedAmount, raw },
      'Scraper extracted usage payload'
    );

    return { success: true, usedAmount, message: raw };
  } catch (error) {
    logger.error({ coupon: coupon.id, error: error.message }, 'Scrape failed');
    return { success: false, error: error.message };
  } finally {
    await driver.quit();
  }
}

module.exports = {
  runScrapeForCoupon
};
