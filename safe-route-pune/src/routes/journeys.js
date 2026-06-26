const express  = require('express');
const { db, nextId } = require('../database');
const { authRequired } = require('../middleware/auth');
const { invalidateCache } = require('./safety');

const router = express.Router();

router.post('/start', authRequired, (req, res) => {
  const { origin, destination, origin_lat, origin_lng, dest_lat, dest_lng,
          route_type, safety_score, distance_m, duration_s, encoded_polyline } = req.body;
  if (!origin||!destination||!route_type)
    return res.status(400).json({ error: 'origin, destination and route_type required' });

  const id      = nextId('journeys');
  const journey = { id, user_id:req.user.id, origin, destination,
    origin_lat, origin_lng, dest_lat, dest_lng, route_type, safety_score,
    distance_m, duration_s, encoded_polyline, started_at:new Date().toISOString(),
    completed_at:null, status:'in_progress' };
  db.get('journeys').push(journey).write();
  res.status(201).json({ journey_id: id });
});

router.patch('/:id/complete', authRequired, (req, res) => {
  const jid = parseInt(req.params.id);
  const j   = db.get('journeys').find({ id:jid, user_id:req.user.id }).value();
  if (!j) return res.status(404).json({ error: 'Journey not found' });
  db.get('journeys').find({ id:jid }).assign({ status:'completed', completed_at:new Date().toISOString() }).write();
  res.json({ message: 'Journey completed' });
});

router.post('/:id/feedback', authRequired, (req, res) => {
  const jid = parseInt(req.params.id);
  const j   = db.get('journeys').find({ id:jid, user_id:req.user.id }).value();
  if (!j) return res.status(404).json({ error: 'Journey not found' });

  const existing = db.get('feedback').find({ journey_id: jid }).value();
  if (existing)  return res.status(409).json({ error: 'Feedback already submitted for this journey' });

  const { overall_rating, safety_rating, lighting_rating, comment,
          felt_unsafe, unsafe_lat, unsafe_lng, unsafe_reason } = req.body;
  if (!overall_rating||!safety_rating)
    return res.status(400).json({ error: 'overall_rating and safety_rating required' });

  const fbId = nextId('feedback');
  db.get('feedback').push({
    id:fbId, journey_id:jid, user_id:req.user.id,
    overall_rating, safety_rating, lighting_rating: lighting_rating||null,
    comment:comment||null, felt_unsafe:!!felt_unsafe,
    unsafe_lat:unsafe_lat||null, unsafe_lng:unsafe_lng||null,
    unsafe_reason:unsafe_reason||null, submitted_at:new Date().toISOString()
  }).write();

  // Update crowdsourced safety model
  if (felt_unsafe && unsafe_lat && unsafe_lng) {
    const adjustment = -((5 - safety_rating) * 2.5);
    const aid = nextId('adjustments');
    db.get('safety_adjustments').push({ id:aid, lat:parseFloat(unsafe_lat), lng:parseFloat(unsafe_lng), adjustment, source:'crowdsource', created_at:new Date().toISOString() }).write();
    invalidateCache();
  } else if (safety_rating >= 4 && j.origin_lat && j.dest_lat) {
    const midLat = (j.origin_lat + j.dest_lat) / 2;
    const midLng = (j.origin_lng + j.dest_lng) / 2;
    const adjustment = (safety_rating - 3) * 1.5;
    const aid = nextId('adjustments');
    db.get('safety_adjustments').push({ id:aid, lat:midLat, lng:midLng, adjustment, source:'crowdsource', created_at:new Date().toISOString() }).write();
    invalidateCache();
  }

  res.status(201).json({ message: 'Feedback submitted. Thank you for keeping Pune safe!' });
});

router.get('/my', authRequired, (req, res) => {
  const journeys = db.get('journeys').filter({ user_id:req.user.id }).value()
    .sort((a,b) => new Date(b.started_at) - new Date(a.started_at))
    .slice(0, 50)
    .map(j => {
      const fb = db.get('feedback').find({ journey_id:j.id }).value();
      return { ...j, overall_rating:fb?.overall_rating||null, safety_rating:fb?.safety_rating||null, comment:fb?.comment||null };
    });
  res.json({ journeys });
});

router.get('/:id', authRequired, (req, res) => {
  const j = db.get('journeys').find({ id:parseInt(req.params.id), user_id:req.user.id }).value();
  if (!j) return res.status(404).json({ error: 'Journey not found' });
  res.json({ journey:j });
});

module.exports = router;
