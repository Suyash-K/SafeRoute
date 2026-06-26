const express  = require('express');
const fs       = require('fs');
const path     = require('path');
const { db }   = require('../database');

const router    = express.Router();
const DATA_PATH = path.join(__dirname, '../../data/pune_safety.json');

let _cache = null;
function getSafetyData() {
  if (_cache) return _cache;
  if (!fs.existsSync(DATA_PATH)) throw new Error('Safety data not found. Run: npm run generate-data');
  _cache = JSON.parse(fs.readFileSync(DATA_PATH, 'utf8'));
  return _cache;
}
function invalidateCache() { _cache = null; }

function haversine(lat1,lng1,lat2,lng2) {
  const R=6371000, p1=lat1*Math.PI/180, p2=lat2*Math.PI/180;
  const dp=(lat2-lat1)*Math.PI/180, dl=(lng2-lng1)*Math.PI/180;
  const a=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
  return R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
}

router.get('/zones', (req, res) => {
  try { const d=getSafetyData(); res.json({ zones:d.zones, metadata:d.metadata }); }
  catch(e) { res.status(503).json({ error: e.message }); }
});

router.get('/heatmap', (req, res) => {
  try {
    const data = getSafetyData();
    const adjs = db.get('safety_adjustments').value() || [];

    let points = data.heatmap_points;
    if (adjs.length > 0) {
      points = points.map(p => {
        let mod = 0;
        for (const a of adjs) {
          const d = haversine(p.lat, p.lng, a.lat, a.lng);
          if (d < 500) mod += a.adjustment * (1 - d/500);
        }
        const newScore  = Math.max(0, Math.min(100, p.safety_score + mod));
        const newWeight = Math.max(0, (100 - newScore) / 100);
        return { ...p, weight:+newWeight.toFixed(3), safety_score:+newScore.toFixed(1) };
      });
    }
    res.json({ heatmap_points: points });
  } catch(e) { res.status(503).json({ error: e.message }); }
});

router.get('/hotspots', (req, res) => {
  try {
    const d = getSafetyData();
    res.json({ accident_hotspots: d.accident_hotspots, crime_hotspots: d.crime_hotspots, women_safety_concerns: d.women_safety_concerns });
  } catch(e) { res.status(503).json({ error: e.message }); }
});

router.post('/score-route', (req, res) => {
  try {
    const { waypoints } = req.body;
    if (!Array.isArray(waypoints)||!waypoints.length)
      return res.status(400).json({ error: 'waypoints array required' });

    const data  = getSafetyData();
    const zones = data.zones;
    const adjs  = db.get('safety_adjustments').value() || [];

    const scores = waypoints.map(wp => {
      let wSum=0, sSum=0;
      for (const z of zones) {
        const d=haversine(wp.lat,wp.lng,z.lat,z.lng), inf=z.radius*1.6;
        if(d<inf){ const w=(1-d/inf)**2; sSum+=z.scores.overall*w; wSum+=w; }
      }
      let base = wSum>0 ? sSum/wSum : 62;
      for (const a of adjs) {
        const d=haversine(wp.lat,wp.lng,a.lat,a.lng);
        if(d<600) base+=a.adjustment*(1-d/600);
      }
      return Math.max(0,Math.min(100,base));
    });

    const avg=scores.reduce((a,b)=>a+b,0)/scores.length;
    const min=Math.min(...scores);
    res.json({ score: Math.round(avg*0.7+min*0.3), segment_scores: scores.map(s=>+s.toFixed(1)) });
  } catch(e) { res.status(500).json({ error: e.message }); }
});

module.exports = { router, invalidateCache };
