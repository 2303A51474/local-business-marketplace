"""API tests: run with  python test_api.py  (uses a temporary database)."""
import os, tempfile, unittest, datetime as dt
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
import app as A

FUT = (dt.date.today() + dt.timedelta(days=3)).isoformat()

class T(unittest.TestCase):
    def setUp(self): self.c = A.app.test_client()
    def login(self, e, p):
        r = self.c.post("/api/auth/login", json={"email": e, "password": p}); self.assertEqual(r.status_code, 200)
        return {"Authorization": "Bearer " + r.get_json()["token"]}

    def test_full_flow(self):
        r = self.c.post("/api/auth/register", json={"name": "T", "email": "t@x.com", "password": "secret1", "role": "customer"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.c.post("/api/auth/register", json={"name": "T", "email": "t@x.com", "password": "secret1", "role": "customer"}).status_code, 409)
        self.assertEqual(self.c.post("/api/auth/login", json={"email": "t@x.com", "password": "bad"}).status_code, 401)
        self.assertEqual(self.c.get("/api/bookings").status_code, 401)
        adm, own, cus, prov = (self.login("admin@demo.com", "admin123"), self.login("owner@demo.com", "owner123"),
                               self.login("customer@demo.com", "customer123"), self.login("provider@demo.com", "provider123"))
        # owner registers business -> cannot add service until verified
        r = self.c.post("/api/businesses", json={"name": "NewBiz", "category": "Beauty", "location": "Warangal"}, headers=own)
        bid = r.get_json()["id"]
        self.assertEqual(self.c.post("/api/services", json={"business_id": bid, "name": "S", "price": 10, "location": "W"}, headers=own).status_code, 403)
        self.assertEqual(self.c.put(f"/api/businesses/{bid}/status", json={"status": "verified"}, headers=own).status_code, 403)
        self.assertEqual(self.c.put(f"/api/businesses/{bid}/status", json={"status": "verified"}, headers=adm).status_code, 200)
        self.assertEqual(self.c.post("/api/services", json={"business_id": bid, "name": "S", "price": 10, "location": "W"}, headers=own).status_code, 201)
        # search
        self.assertGreaterEqual(len(self.c.get("/api/services?q=Hair", headers=cus).get_json()), 1)
        # booking validations
        self.assertEqual(self.c.post("/api/bookings", json={"service_id": 1, "date": "2020-01-01", "time": "10:00"}, headers=cus).status_code, 400)
        r = self.c.post("/api/bookings", json={"service_id": 1, "date": FUT, "time": "10:00"}, headers=cus); self.assertEqual(r.status_code, 201)
        b = r.get_json()["id"]
        self.assertEqual(self.c.post("/api/bookings", json={"service_id": 1, "date": FUT, "time": "10:00"}, headers=cus).status_code, 409)
        self.assertEqual(self.c.put(f"/api/bookings/{b}/reschedule", json={"date": FUT, "time": "11:00"}, headers=cus).status_code, 200)
        self.assertEqual(self.c.put(f"/api/bookings/{b}/status", json={"status": "completed"}, headers=prov).status_code, 409)
        self.assertEqual(self.c.put(f"/api/bookings/{b}/status", json={"status": "confirmed"}, headers=prov).status_code, 200)
        self.assertEqual(self.c.post(f"/api/bookings/{b}/pay", json={"method": "upi"}, headers=cus).status_code, 200)
        self.assertEqual(self.c.post(f"/api/bookings/{b}/pay", json={}, headers=cus).status_code, 409)
        self.assertEqual(self.c.post("/api/reviews", json={"booking_id": b, "rating": 5}, headers=cus).status_code, 409)
        self.assertEqual(self.c.put(f"/api/bookings/{b}/status", json={"status": "completed"}, headers=own).status_code, 200)
        self.assertEqual(self.c.post("/api/reviews", json={"booking_id": b, "rating": 5, "comment": "Great"}, headers=cus).status_code, 201)
        # dashboard + reports + role restriction
        for h in (adm, own, cus, prov): self.assertEqual(self.c.get("/api/dashboard", headers=h).status_code, 200)
        for n in ("business-registration", "service-booking", "revenue", "customer-feedback"):
            self.assertEqual(self.c.get(f"/api/reports/{n}", headers=adm).status_code, 200)
            r = self.c.get(f"/api/reports/{n}?format=csv", headers=own); self.assertEqual(r.status_code, 200); self.assertIn("text/csv", r.content_type)
        self.assertEqual(self.c.get("/api/reports/revenue", headers=cus).status_code, 403)
        self.assertEqual(self.c.get("/api/reports/nope", headers=adm).status_code, 404)
        self.assertEqual(self.c.get("/api/health").status_code, 200)
        self.assertEqual(self.c.get("/").status_code, 200)

if __name__ == "__main__": unittest.main(verbosity=2)
