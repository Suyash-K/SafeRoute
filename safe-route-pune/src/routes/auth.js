const express  = require('express');
const bcrypt   = require('bcryptjs');
const jwt      = require('jsonwebtoken');
const { db, nextId } = require('../database');

const router     = express.Router();
const JWT_SECRET = process.env.JWT_SECRET || 'pune_safe_route_secret';
const JWT_EXP    = process.env.JWT_EXPIRES_IN || '7d';

// POST /api/auth/register
router.post('/register', async (req, res) => {
  try {
    const { name, email, password } = req.body;
    if (!name || !email || !password)
      return res.status(400).json({ error: 'name, email and password are required' });
    if (password.length < 6)
      return res.status(400).json({ error: 'Password must be at least 6 characters' });

    const exists = db.get('users').find({ email: email.toLowerCase().trim() }).value();
    if (exists) return res.status(409).json({ error: 'An account with this email already exists' });

    const hash = await bcrypt.hash(password, 12);
    const id   = nextId('users');
    const user = { id, name: name.trim(), email: email.toLowerCase().trim(), password: hash, created_at: new Date().toISOString(), last_login: null };
    db.get('users').push(user).write();

    const token = jwt.sign({ id, email: user.email, name: user.name }, JWT_SECRET, { expiresIn: JWT_EXP });
    res.status(201).json({ token, user: { id, name: user.name, email: user.email } });
  } catch (err) { console.error(err); res.status(500).json({ error: 'Registration failed' }); }
});

// POST /api/auth/login
router.post('/login', async (req, res) => {
  try {
    const { email, password } = req.body;
    if (!email || !password) return res.status(400).json({ error: 'Email and password required' });

    const user = db.get('users').find({ email: email.toLowerCase().trim() }).value();
    if (!user) return res.status(401).json({ error: 'Invalid email or password' });

    const match = await bcrypt.compare(password, user.password);
    if (!match)  return res.status(401).json({ error: 'Invalid email or password' });

    db.get('users').find({ id: user.id }).assign({ last_login: new Date().toISOString() }).write();

    const token = jwt.sign({ id: user.id, email: user.email, name: user.name }, JWT_SECRET, { expiresIn: JWT_EXP });
    res.json({ token, user: { id: user.id, name: user.name, email: user.email } });
  } catch (err) { console.error(err); res.status(500).json({ error: 'Login failed' }); }
});

// GET /api/auth/me
const { authRequired } = require('../middleware/auth');
router.get('/me', authRequired, (req, res) => {
  const user = db.get('users').find({ id: req.user.id }).value();
  if (!user) return res.status(404).json({ error: 'User not found' });
  const { password, ...safe } = user;
  res.json({ user: safe });
});

module.exports = router;
