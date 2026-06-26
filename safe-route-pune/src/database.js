const low      = require('lowdb');
const FileSync = require('lowdb/adapters/FileSync');
const path     = require('path');
const fs       = require('fs');

const DATA_DIR = path.join(__dirname, '../data');
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

const adapter = new FileSync(path.join(DATA_DIR, 'db.json'));
const db      = low(adapter);

function initDatabase() {
  db.defaults({
    users:               [],
    journeys:            [],
    feedback:            [],
    safety_adjustments:  [],
    _counters: { users: 0, journeys: 0, feedback: 0, adjustments: 0 }
  }).write();
  console.log('✓ Database initialised (data/db.json)');
  return db;
}

function nextId(collection) {
  const key = collection;
  const current = db.get(`_counters.${key}`).value() || 0;
  const next    = current + 1;
  db.set(`_counters.${key}`, next).write();
  return next;
}

module.exports = { db, initDatabase, nextId };
