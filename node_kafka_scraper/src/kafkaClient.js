const { Kafka } = require('kafkajs');
const logger = require('./logger');

const getBrokers = () => {
  const raw = process.env.KAFKA_BROKERS || 'localhost:9092';
  return raw.split(',').map((item) => item.trim()).filter(Boolean);
};

const clientId = process.env.KAFKA_CLIENT_ID || 'coupon-kafka-scraper';

function buildKafkaClient() {
  const brokers = getBrokers();
  if (!brokers.length) {
    throw new Error('KAFKA_BROKERS must contain at least one broker address');
  }
  return new Kafka({ clientId, brokers });
}

async function connectConsumer(topic, groupId) {
  const kafka = buildKafkaClient();
  const consumer = kafka.consumer({ groupId: groupId || process.env.KAFKA_GROUP || 'coupon-scraper-group' });
  await consumer.connect();
  await consumer.subscribe({ topic, fromBeginning: false });
  logger.info({ topic, groupId: consumer.groupId }, 'Kafka consumer connected');
  return consumer;
}

async function connectProducer() {
  const kafka = buildKafkaClient();
  const producer = kafka.producer();
  await producer.connect();
  logger.info('Kafka producer connected');
  return producer;
}

module.exports = {
  connectConsumer,
  connectProducer
};
