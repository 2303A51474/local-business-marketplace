# Local Business Marketplace and Service Booking Platform

**Course:** DevOps & Full Stack Development, B.Tech IV Year I Sem, AY 2026-27, SR University
**Student:** Habeeba Khanam | **Enrolment No:** 2303A51474 | **Project #10**

## 1. Objectives
Build a full-stack web application where local businesses and service providers register (and are verified by an admin), list services with prices, locations and availability, and customers search, book, reschedule, pay (simulated) and review services. The app is containerised with Docker and deployed on Kubernetes.

## 2. Requirements coverage (SRS #10)
| SRS requirement | Where implemented |
|---|---|
| Register and verify local businesses and service providers | Owners/providers register; admin verifies/rejects businesses (Businesses screen) |
| List services, prices, locations, availability | My Services screen (owner), `services` table |
| Customers search, book, reschedule services | Find Services (search by keyword/category/location), My Bookings (reschedule/cancel); double-booking prevented |
| Booking status, payment simulation, reviews | pending → confirmed → completed / cancelled; Pay (simulated); Review after completion |
| Roles: Admin, Business Owner, Customer, Service Provider | JWT auth + role-based authorization on every endpoint |
| Reports: Business Registration, Service Booking, Revenue, Customer Feedback | Reports screen; view, **Export CSV**, **Print** |
| Dashboard with cards, tables, visualisations | Role-specific stat cards, bar charts, recent bookings |
| Min. 9 screens | 11 (Login, Register, Dashboard, Businesses, Services, Bookings, Payments, Feedback, Reports, Users, Booking form) |

## 3. Technology stack
Frontend: HTML, CSS, vanilla JavaScript (responsive single-page app) · Backend: Python 3.12, Flask REST API, PyJWT, Gunicorn · Database: SQLite (file DB, persisted on a volume/PVC) · DevOps: Git/GitHub, Docker, Docker Compose, Kubernetes.

## 4. Architecture
```
Browser (SPA)  --HTTP/JSON + JWT-->  Flask REST API (Gunicorn)  -->  SQLite (/data/app.db)
                                      serves static UI at "/"
Kubernetes:  Service (NodePort 30080) -> Deployment (1 pod) -> PVC (/data)
```

## 5. Database design
- `users(id, name, email*, password_hash, role, created_at)`
- `businesses(id, owner_id→users, name, category, location, description, status, created_at)`
- `services(id, business_id→businesses, provider_id→users, name, description, price, location, availability, active)`
- `bookings(id, customer_id→users, service_id→services, date, time, status, payment_status, amount, created_at)`
- `payments(id, booking_id→bookings, amount, method, status, created_at)`
- `reviews(id, booking_id* →bookings, customer_id, service_id, rating 1-5, comment, created_at)`

## 6. API details (all `/api`, JSON, `Authorization: Bearer <token>` except auth)
| Method & path | Role | Purpose |
|---|---|---|
| POST `/auth/register`, `/auth/login` | public | register / login (returns JWT) |
| GET `/me`, GET `/users` | any / admin, owner | profile, user list |
| GET/POST `/businesses`, PUT `/businesses/{id}/status` | any / owner / admin | list, register, verify |
| GET/POST `/services`, PUT/DELETE `/services/{id}` | any / owner | search (q, category, location), manage |
| GET/POST `/bookings`, PUT `/bookings/{id}/status`, PUT `/bookings/{id}/reschedule`, POST `/bookings/{id}/pay` | scoped by role | booking lifecycle |
| GET `/payments`, GET/POST `/reviews` | scoped by role | payments, feedback |
| GET `/dashboard` | any | role-specific summary |
| GET `/reports/{business-registration\|service-booking\|revenue\|customer-feedback}[?format=csv]` | admin, owner | reports |
| GET `/health` | public | liveness probe |

Errors return `{"error": "..."}` with 400/401/403/404/409 codes.

## 7. Demo accounts (seeded automatically)
admin@demo.com / admin123 · owner@demo.com / owner123 · provider@demo.com / provider123 · customer@demo.com / customer123

## 8. Run locally
```bash
cd backend
pip install -r requirements.txt
python app.py            # http://localhost:5000
python test_api.py       # automated tests
```

## 9. GitHub
```bash
git init && git add . && git commit -m "Initial commit: Flask API + SPA"
git branch -M main
git remote add origin https://github.com/<your-username>/local-business-marketplace.git
git push -u origin main
```
Use meaningful, separate commits (see section 12) so the commit history is clear.

## 10. Docker
```bash
cd backend
docker build -t local-marketplace:1.0 .
docker run -d -p 5000:5000 -v mkt_data:/data -e JWT_SECRET=mysecret --name mkt local-marketplace:1.0
# open http://localhost:5000
# or from project root:  docker compose up --build
```

## 11. Kubernetes (Minikube / Docker Desktop / kind)
```bash
# Minikube: build the image inside minikube's Docker
minikube start
eval $(minikube docker-env)          # Windows PowerShell: & minikube -p minikube docker-env | Invoke-Expression
docker build -t local-marketplace:1.0 ./backend

kubectl apply -f k8s/secret.yaml -f k8s/pvc.yaml -f k8s/deployment.yaml -f k8s/service.yaml
kubectl get pods,svc
minikube service marketplace-service --url      # open this URL
# Docker Desktop Kubernetes: open http://localhost:30080
# kind: kind load docker-image local-marketplace:1.0, then http://localhost:30080 via port-forward:
#   kubectl port-forward svc/marketplace-service 8080:80
```
Cleanup: `kubectl delete -f k8s/`

## 12. Suggested commit history
1. `chore: project structure and .gitignore` 2. `feat: database schema and auth` 3. `feat: businesses and services APIs` 4. `feat: bookings, payments, reviews` 5. `feat: dashboard and reports` 6. `feat: frontend SPA` 7. `test: API tests` 8. `build: Dockerfile and compose` 9. `deploy: Kubernetes manifests` 10. `docs: README`

## 13. Testing
`python backend/test_api.py` covers registration, duplicate email, login, auth/role checks, business verification, service creation rules, search, booking validation, double-booking conflict, reschedule, status rules, payment, review, dashboards, all 4 reports (JSON + CSV). Result: **OK**. Take screenshots of: each role dashboard, a booking flow, reports, `docker ps`, `kubectl get pods,svc`.

## 14. Demonstration checklist
Login as owner → register business → login as admin → verify → owner adds service → customer searches and books → provider/owner confirms and completes → customer pays and reviews → admin/owner view dashboard and reports (CSV/print) → show Docker build/run → show `kubectl get pods,svc` and the app via the Service URL.

## 15. Limitations / future work
SQLite is single-writer (1 replica); for scale use PostgreSQL. Payment is simulated. No email notifications.
