"""Local Business Marketplace and Service Booking Platform - REST API (Flask + SQLite)."""
import csv, io, os, sqlite3, datetime as dt
from functools import wraps
import jwt
from flask import Flask, g, jsonify, request, send_from_directory, Response
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder="static", static_url_path="/static")
SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "app.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS businesses(id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL REFERENCES users(id),
  name TEXT NOT NULL, category TEXT NOT NULL, location TEXT NOT NULL, description TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS services(id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL REFERENCES businesses(id),
  provider_id INTEGER REFERENCES users(id), name TEXT NOT NULL, description TEXT DEFAULT '', price REAL NOT NULL,
  location TEXT NOT NULL, availability TEXT DEFAULT 'Mon-Sat 09:00-18:00', active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS bookings(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL REFERENCES users(id),
  service_id INTEGER NOT NULL REFERENCES services(id), date TEXT NOT NULL, time TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', payment_status TEXT NOT NULL DEFAULT 'unpaid', amount REAL NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, booking_id INTEGER NOT NULL REFERENCES bookings(id),
  amount REAL NOT NULL, method TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY AUTOINCREMENT, booking_id INTEGER UNIQUE NOT NULL REFERENCES bookings(id),
  customer_id INTEGER NOT NULL, service_id INTEGER NOT NULL, rating INTEGER NOT NULL, comment TEXT DEFAULT '', created_at TEXT NOT NULL);
"""

def now(): return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d: d.close()

def q(sql, args=(), one=False):
    rows = [dict(r) for r in db().execute(sql, args).fetchall()]
    return (rows[0] if rows else None) if one else rows

def run(sql, args=()):
    c = db().execute(sql, args); db().commit(); return c.lastrowid

def err(msg, code=400): return jsonify({"error": msg}), code

def auth(*roles):
    def deco(f):
        @wraps(f)
        def wrap(*a, **kw):
            h = request.headers.get("Authorization", "")
            if not h.startswith("Bearer "): return err("Authentication required", 401)
            try: data = jwt.decode(h[7:], SECRET, algorithms=["HS256"])
            except jwt.PyJWTError: return err("Invalid or expired token", 401)
            u = q("SELECT id,name,email,role FROM users WHERE id=?", (data["uid"],), one=True)
            if not u: return err("User not found", 401)
            if roles and u["role"] not in roles: return err("Access denied for your role", 403)
            g.user = u
            return f(*a, **kw)
        return wrap
    return deco

def body(*required):
    d = request.get_json(silent=True) or {}
    missing = [k for k in required if str(d.get(k, "")).strip() == ""]
    return d, missing

# ---------------- Auth ----------------
@app.post("/api/auth/register")
def register():
    d, m = body("name", "email", "password", "role")
    if m: return err("Missing fields: " + ", ".join(m))
    if d["role"] not in ("owner", "customer", "provider"): return err("Role must be owner, customer or provider")
    if "@" not in d["email"] or len(d["password"]) < 6: return err("Valid email and password (min 6 chars) required")
    if q("SELECT 1 FROM users WHERE email=?", (d["email"].lower(),), one=True): return err("Email already registered", 409)
    run("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
        (d["name"].strip(), d["email"].lower(), generate_password_hash(d["password"]), d["role"], now()))
    return jsonify({"message": "Registered successfully"}), 201

@app.post("/api/auth/login")
def login():
    d, m = body("email", "password")
    if m: return err("Email and password required")
    u = q("SELECT * FROM users WHERE email=?", (d["email"].lower(),), one=True)
    if not u or not check_password_hash(u["password_hash"], d["password"]): return err("Invalid credentials", 401)
    tok = jwt.encode({"uid": u["id"], "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)}, SECRET, algorithm="HS256")
    return jsonify({"token": tok, "user": {"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"]}})

@app.get("/api/me")
@auth()
def me(): return jsonify(g.user)

@app.get("/api/users")
@auth("admin", "owner")
def users():
    if g.user["role"] == "owner":
        return jsonify(q("SELECT id,name,email,role FROM users WHERE role='provider'"))
    return jsonify(q("SELECT id,name,email,role,created_at FROM users ORDER BY id"))

# ---------------- Businesses ----------------
@app.get("/api/businesses")
@auth()
def businesses():
    r = g.user["role"]
    base = "SELECT b.*, u.name owner_name FROM businesses b JOIN users u ON u.id=b.owner_id"
    if r == "admin": rows = q(base + " ORDER BY b.id DESC")
    elif r == "owner": rows = q(base + " WHERE b.owner_id=? ORDER BY b.id DESC", (g.user["id"],))
    else: rows = q(base + " WHERE b.status='verified' ORDER BY b.id DESC")
    return jsonify(rows)

@app.post("/api/businesses")
@auth("owner")
def add_business():
    d, m = body("name", "category", "location")
    if m: return err("Missing fields: " + ", ".join(m))
    i = run("INSERT INTO businesses(owner_id,name,category,location,description,status,created_at) VALUES(?,?,?,?,?,'pending',?)",
            (g.user["id"], d["name"], d["category"], d["location"], d.get("description", ""), now()))
    return jsonify({"id": i, "message": "Business registered; awaiting admin verification"}), 201

@app.put("/api/businesses/<int:bid>/status")
@auth("admin")
def verify_business(bid):
    d, m = body("status")
    if m or d["status"] not in ("verified", "rejected", "pending"): return err("Status must be verified, rejected or pending")
    if not q("SELECT 1 FROM businesses WHERE id=?", (bid,), one=True): return err("Business not found", 404)
    run("UPDATE businesses SET status=? WHERE id=?", (d["status"], bid))
    return jsonify({"message": "Status updated"})

# ---------------- Services ----------------
@app.get("/api/services")
@auth()
def services():
    sql = ("SELECT s.*, b.name business_name, b.category, b.status business_status, p.name provider_name, "
           "(SELECT ROUND(AVG(rating),1) FROM reviews r WHERE r.service_id=s.id) avg_rating "
           "FROM services s JOIN businesses b ON b.id=s.business_id LEFT JOIN users p ON p.id=s.provider_id WHERE 1=1")
    a = []
    r = g.user["role"]
    if r == "owner": sql += " AND b.owner_id=?"; a.append(g.user["id"])
    elif r != "admin": sql += " AND b.status='verified' AND s.active=1"
    if request.args.get("q"):
        sql += " AND (s.name LIKE ? OR s.description LIKE ? OR b.name LIKE ?)"; k = f"%{request.args['q']}%"; a += [k, k, k]
    if request.args.get("category"): sql += " AND b.category=?"; a.append(request.args["category"])
    if request.args.get("location"): sql += " AND s.location LIKE ?"; a.append(f"%{request.args['location']}%")
    return jsonify(q(sql + " ORDER BY s.id DESC", a))

@app.post("/api/services")
@auth("owner")
def add_service():
    d, m = body("business_id", "name", "price", "location")
    if m: return err("Missing fields: " + ", ".join(m))
    try:
        price = float(d["price"]); assert price >= 0
    except Exception: return err("Price must be a non-negative number")
    b = q("SELECT * FROM businesses WHERE id=? AND owner_id=?", (d["business_id"], g.user["id"]), one=True)
    if not b: return err("Business not found or not yours", 404)
    if b["status"] != "verified": return err("Business must be verified by admin first", 403)
    i = run("INSERT INTO services(business_id,provider_id,name,description,price,location,availability) VALUES(?,?,?,?,?,?,?)",
            (b["id"], d.get("provider_id") or None, d["name"], d.get("description", ""), price, d["location"],
             d.get("availability") or "Mon-Sat 09:00-18:00"))
    return jsonify({"id": i, "message": "Service added"}), 201

@app.put("/api/services/<int:sid>")
@auth("owner")
def edit_service(sid):
    s = q("SELECT s.* FROM services s JOIN businesses b ON b.id=s.business_id WHERE s.id=? AND b.owner_id=?", (sid, g.user["id"]), one=True)
    if not s: return err("Service not found", 404)
    d = request.get_json(silent=True) or {}
    try:
        price = float(d.get("price", s["price"])); assert price >= 0
    except Exception: return err("Invalid price")
    run("UPDATE services SET name=?,description=?,price=?,location=?,availability=?,provider_id=?,active=? WHERE id=?",
        (d.get("name", s["name"]), d.get("description", s["description"]), price, d.get("location", s["location"]),
         d.get("availability", s["availability"]), d.get("provider_id", s["provider_id"]) or None, int(d.get("active", s["active"])), sid))
    return jsonify({"message": "Service updated"})

@app.delete("/api/services/<int:sid>")
@auth("owner")
def del_service(sid):
    s = q("SELECT s.id FROM services s JOIN businesses b ON b.id=s.business_id WHERE s.id=? AND b.owner_id=?", (sid, g.user["id"]), one=True)
    if not s: return err("Service not found", 404)
    run("UPDATE services SET active=0 WHERE id=?", (sid,))
    return jsonify({"message": "Service deactivated"})

# ---------------- Bookings ----------------
BK_SQL = ("SELECT bk.*, s.name service_name, b.name business_name, b.owner_id, s.provider_id, c.name customer_name "
          "FROM bookings bk JOIN services s ON s.id=bk.service_id JOIN businesses b ON b.id=s.business_id "
          "JOIN users c ON c.id=bk.customer_id")

def scope():
    r, uid = g.user["role"], g.user["id"]
    if r == "admin": return " WHERE 1=1", []
    if r == "owner": return " WHERE b.owner_id=?", [uid]
    if r == "provider": return " WHERE s.provider_id=?", [uid]
    return " WHERE bk.customer_id=?", [uid]

def valid_slot(date, time_):
    try: when = dt.datetime.strptime(f"{date} {time_}", "%Y-%m-%d %H:%M")
    except ValueError: return "Date must be YYYY-MM-DD and time HH:MM"
    if when < dt.datetime.now(): return "Booking date/time must be in the future"

def clash(sid, date, time_, ignore=None):
    return q("SELECT 1 FROM bookings WHERE service_id=? AND date=? AND time=? AND status!='cancelled' AND id!=?",
             (sid, date, time_, ignore or 0), one=True)

@app.get("/api/bookings")
@auth()
def bookings():
    w, a = scope()
    return jsonify(q(BK_SQL + w + " ORDER BY bk.id DESC", a))

@app.post("/api/bookings")
@auth("customer")
def book():
    d, m = body("service_id", "date", "time")
    if m: return err("Missing fields: " + ", ".join(m))
    e = valid_slot(d["date"], d["time"])
    if e: return err(e)
    s = q("SELECT s.*, b.status bs FROM services s JOIN businesses b ON b.id=s.business_id WHERE s.id=?", (d["service_id"],), one=True)
    if not s or not s["active"] or s["bs"] != "verified": return err("Service not available", 404)
    if clash(s["id"], d["date"], d["time"]): return err("That slot is already booked. Choose another time.", 409)
    i = run("INSERT INTO bookings(customer_id,service_id,date,time,amount,created_at) VALUES(?,?,?,?,?,?)",
            (g.user["id"], s["id"], d["date"], d["time"], s["price"], now()))
    return jsonify({"id": i, "message": "Booking created"}), 201

def get_booking(bid):
    w, a = scope()
    return q(BK_SQL + w + " AND bk.id=?", a + [bid], one=True)

@app.put("/api/bookings/<int:bid>/status")
@auth()
def booking_status(bid):
    b = get_booking(bid)
    if not b: return err("Booking not found", 404)
    d, m = body("status")
    st = d.get("status")
    if m or st not in ("confirmed", "completed", "cancelled"): return err("Status must be confirmed, completed or cancelled")
    if g.user["role"] == "customer" and st != "cancelled": return err("Customers can only cancel", 403)
    if b["status"] in ("cancelled", "completed"): return err(f"Booking already {b['status']}", 409)
    if st == "completed" and b["status"] != "confirmed": return err("Only confirmed bookings can be completed", 409)
    run("UPDATE bookings SET status=? WHERE id=?", (st, bid))
    return jsonify({"message": f"Booking {st}"})

@app.put("/api/bookings/<int:bid>/reschedule")
@auth("customer")
def reschedule(bid):
    b = get_booking(bid)
    if not b: return err("Booking not found", 404)
    if b["status"] in ("cancelled", "completed"): return err("Cannot reschedule this booking", 409)
    d, m = body("date", "time")
    if m: return err("Date and time required")
    e = valid_slot(d["date"], d["time"])
    if e: return err(e)
    if clash(b["service_id"], d["date"], d["time"], bid): return err("That slot is already booked", 409)
    run("UPDATE bookings SET date=?,time=?,status='pending' WHERE id=?", (d["date"], d["time"], bid))
    return jsonify({"message": "Booking rescheduled"})

@app.post("/api/bookings/<int:bid>/pay")
@auth("customer")
def pay(bid):
    b = get_booking(bid)
    if not b: return err("Booking not found", 404)
    if b["status"] == "cancelled": return err("Cannot pay for a cancelled booking", 409)
    if b["payment_status"] == "paid": return err("Already paid", 409)
    method = (request.get_json(silent=True) or {}).get("method", "card")
    if method not in ("card", "upi", "netbanking", "wallet"): return err("Invalid payment method")
    run("INSERT INTO payments(booking_id,amount,method,status,created_at) VALUES(?,?,?,'success',?)", (bid, b["amount"], method, now()))
    run("UPDATE bookings SET payment_status='paid' WHERE id=?", (bid,))
    return jsonify({"message": "Payment successful (simulated)"})

@app.get("/api/payments")
@auth()
def payments():
    w, a = scope()
    return jsonify(q("SELECT p.*, s.name service_name, c.name customer_name FROM payments p JOIN bookings bk ON bk.id=p.booking_id "
                     "JOIN services s ON s.id=bk.service_id JOIN businesses b ON b.id=s.business_id JOIN users c ON c.id=bk.customer_id"
                     + w + " ORDER BY p.id DESC", a))

# ---------------- Reviews ----------------
@app.post("/api/reviews")
@auth("customer")
def review():
    d, m = body("booking_id", "rating")
    if m: return err("Booking and rating required")
    try:
        rating = int(d["rating"]); assert 1 <= rating <= 5
    except Exception: return err("Rating must be 1-5")
    b = q("SELECT * FROM bookings WHERE id=? AND customer_id=?", (d["booking_id"], g.user["id"]), one=True)
    if not b: return err("Booking not found", 404)
    if b["status"] != "completed": return err("You can review only completed bookings", 409)
    if q("SELECT 1 FROM reviews WHERE booking_id=?", (b["id"],), one=True): return err("Already reviewed", 409)
    run("INSERT INTO reviews(booking_id,customer_id,service_id,rating,comment,created_at) VALUES(?,?,?,?,?,?)",
        (b["id"], g.user["id"], b["service_id"], rating, d.get("comment", ""), now()))
    return jsonify({"message": "Thank you for your feedback"}), 201

REV_SQL = ("SELECT r.id, r.rating, r.comment, r.created_at, c.name customer_name, s.name service_name, b.name business_name "
           "FROM reviews r JOIN users c ON c.id=r.customer_id JOIN services s ON s.id=r.service_id JOIN businesses b ON b.id=s.business_id")

@app.get("/api/reviews")
@auth()
def reviews():
    r, uid = g.user["role"], g.user["id"]
    if r == "owner": return jsonify(q(REV_SQL + " WHERE b.owner_id=? ORDER BY r.id DESC", (uid,)))
    if r == "provider": return jsonify(q(REV_SQL + " WHERE s.provider_id=? ORDER BY r.id DESC", (uid,)))
    if r == "customer": return jsonify(q(REV_SQL + " WHERE r.customer_id=? ORDER BY r.id DESC", (uid,)))
    return jsonify(q(REV_SQL + " ORDER BY r.id DESC"))

# ---------------- Dashboard ----------------
@app.get("/api/dashboard")
@auth()
def dashboard():
    r, uid = g.user["role"], g.user["id"]
    w, a = scope()
    bk = q(BK_SQL + w + " ORDER BY bk.id DESC", a)
    by_status = {}
    for x in bk: by_status[x["status"]] = by_status.get(x["status"], 0) + 1
    paid = round(sum(x["amount"] for x in bk if x["payment_status"] == "paid"), 2)
    cards = {"Total Bookings": len(bk), "Pending": by_status.get("pending", 0), "Completed": by_status.get("completed", 0),
             ("Total Spent" if r == "customer" else "Revenue"): paid}
    chart2, t2 = {}, "Bookings per service"
    if r == "admin":
        cards.update({"Users": q("SELECT COUNT(*) n FROM users", one=True)["n"],
                      "Businesses": q("SELECT COUNT(*) n FROM businesses", one=True)["n"],
                      "Pending Verification": q("SELECT COUNT(*) n FROM businesses WHERE status='pending'", one=True)["n"]})
        chart2 = {x["category"]: x["n"] for x in q("SELECT category, COUNT(*) n FROM businesses GROUP BY category")}
        t2 = "Businesses by category"
    elif r == "owner":
        cards.update({"My Businesses": q("SELECT COUNT(*) n FROM businesses WHERE owner_id=?", (uid,), one=True)["n"],
                      "My Services": q("SELECT COUNT(*) n FROM services s JOIN businesses b ON b.id=s.business_id WHERE b.owner_id=?", (uid,), one=True)["n"]})
        chart2 = {x["name"]: x["n"] for x in q("SELECT s.name, COUNT(bk.id) n FROM services s JOIN businesses b ON b.id=s.business_id "
                                                "LEFT JOIN bookings bk ON bk.service_id=s.id WHERE b.owner_id=? GROUP BY s.id", (uid,))}
    return jsonify({"cards": cards, "chart": {"title": "Bookings by status", "data": by_status},
                    "chart2": {"title": t2, "data": chart2}, "recent": bk[:5]})

# ---------------- Reports ----------------
def report_data(name):
    owner = g.user["role"] == "owner"
    own, a = (" AND b.owner_id=?", [g.user["id"]]) if owner else ("", [])
    if name == "business-registration":
        return q("SELECT b.id 'ID', b.name 'Business', b.category 'Category', b.location 'Location', u.name 'Owner', b.status 'Status', b.created_at 'Registered On' "
                 "FROM businesses b JOIN users u ON u.id=b.owner_id WHERE 1=1" + own + " ORDER BY b.id", a)
    if name == "service-booking":
        return q("SELECT bk.id 'Booking ID', c.name 'Customer', s.name 'Service', b.name 'Business', bk.date 'Date', bk.time 'Time', "
                 "bk.status 'Status', bk.payment_status 'Payment', bk.amount 'Amount' FROM bookings bk JOIN services s ON s.id=bk.service_id "
                 "JOIN businesses b ON b.id=s.business_id JOIN users c ON c.id=bk.customer_id WHERE 1=1" + own + " ORDER BY bk.id", a)
    if name == "revenue":
        return q("SELECT b.name 'Business', COUNT(p.id) 'Paid Bookings', ROUND(COALESCE(SUM(p.amount),0),2) 'Revenue' FROM businesses b "
                 "LEFT JOIN services s ON s.business_id=b.id LEFT JOIN bookings bk ON bk.service_id=s.id LEFT JOIN payments p ON p.booking_id=bk.id "
                 "AND p.status='success' WHERE 1=1" + own + " GROUP BY b.id ORDER BY 3 DESC", a)
    if name == "customer-feedback":
        return q("SELECT r.id 'ID', c.name 'Customer', s.name 'Service', b.name 'Business', r.rating 'Rating', r.comment 'Comment', r.created_at 'Date' "
                 "FROM reviews r JOIN users c ON c.id=r.customer_id JOIN services s ON s.id=r.service_id JOIN businesses b ON b.id=s.business_id "
                 "WHERE 1=1" + own + " ORDER BY r.id DESC", a)

@app.get("/api/reports/<name>")
@auth("admin", "owner")
def report(name):
    rows = report_data(name)
    if rows is None: return err("Unknown report", 404)
    if request.args.get("format") == "csv":
        out = io.StringIO()
        if rows:
            w = csv.DictWriter(out, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={name}.csv"})
    return jsonify(rows)

@app.get("/api/health")
def health(): return jsonify({"status": "ok"})

@app.get("/")
def index(): return send_from_directory(app.static_folder, "index.html")

# ---------------- Init & seed ----------------
def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    c = sqlite3.connect(DB_PATH); c.executescript(SCHEMA)
    if not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        def u(n, e, p, r):
            return c.execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                             (n, e, generate_password_hash(p), r, now())).lastrowid
        def b(o, n, cat, loc, d, st):
            return c.execute("INSERT INTO businesses(owner_id,name,category,location,description,status,created_at) VALUES(?,?,?,?,?,?,?)",
                             (o, n, cat, loc, d, st, now())).lastrowid
        u("Admin", "admin@demo.com", "admin123", "admin")
        o = u("Ravi Owner", "owner@demo.com", "owner123", "owner")
        p = u("Sita Provider", "provider@demo.com", "provider123", "provider")
        u("Anil Customer", "customer@demo.com", "customer123", "customer")
        b1 = b(o, "Glow Salon", "Beauty", "Warangal", "Hair and skin care", "verified")
        b2 = b(o, "QuickFix Home Services", "Home Repair", "Hanamkonda", "Plumbing and electrical", "verified")
        b(o, "Green Tutors", "Education", "Warangal", "Home tuition", "pending")
        for bid, n, d, pr, l in [(b1, "Haircut", "Standard haircut", 250, "Warangal"), (b1, "Facial", "Deep cleansing facial", 700, "Warangal"),
                                 (b2, "Plumbing Visit", "Leak repair", 400, "Hanamkonda"), (b2, "Electrician Visit", "Wiring check", 350, "Hanamkonda")]:
            c.execute("INSERT INTO services(business_id,provider_id,name,description,price,location) VALUES(?,?,?,?,?,?)", (bid, p, n, d, pr, l))
        c.commit()
    c.close()

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
