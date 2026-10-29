from decimal import Decimal
import uuid

from fastapi.testclient import TestClient

from main import app
from models.enquiry import EnquiryStatus, FailureReason


def test_create_enquiry(session):
    with TestClient(app) as client:
        payload = {
            "listing_id": str(uuid.uuid4()),
            "buyer_business_id": str(uuid.uuid4()),
            "seller_business_id": str(uuid.uuid4()),
            "quantity": "10.000",
            "unit": "kg",
            "unit_price": "5.0000",
        }
        response = client.post("/api/v1/enquiries/", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == EnquiryStatus.ENQUIRY.value
    assert data["quantity"] == "10.000"
    assert data["unit_price"] == "5.0000"
    assert Decimal(data["total_amount"]) == Decimal("50.0000")


def test_list_enquiries(session):
    with TestClient(app) as client:
        response = client.get("/api/v1/enquiries/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_enquiry_not_found(session):
    with TestClient(app) as client:
        response = client.get(f"/api/v1/enquiries/{uuid.uuid4()}")
    assert response.status_code == 404


def test_accept_enquiry(session):
    with TestClient(app) as client:
        payload = {
            "listing_id": str(uuid.uuid4()),
            "buyer_business_id": str(uuid.uuid4()),
            "seller_business_id": str(uuid.uuid4()),
            "quantity": "2.000",
            "unit": "kg",
            "unit_price": "10.0000",
        }
        create_resp = client.post("/api/v1/enquiries/", json=payload)
        enquiry_id = create_resp.json()["enquiry_id"]
        response = client.post(f"/api/v1/enquiries/{enquiry_id}/accept")
    assert response.status_code == 200
    assert response.json()["status"] == EnquiryStatus.AGREED.value
    assert response.json()["accepted_at"] is not None


def test_open_enquiry(session):
    with TestClient(app) as client:
        payload = {
            "listing_id": str(uuid.uuid4()),
            "buyer_business_id": str(uuid.uuid4()),
            "seller_business_id": str(uuid.uuid4()),
            "quantity": "1.000",
            "unit": "kg",
            "unit_price": "3.0000",
        }
        create_resp = client.post("/api/v1/enquiries/", json=payload)
        enquiry_id = create_resp.json()["enquiry_id"]
        client.post(f"/api/v1/enquiries/{enquiry_id}/accept")
        response = client.post(f"/api/v1/enquiries/{enquiry_id}/open")
    assert response.status_code == 200
    assert response.json()["status"] == EnquiryStatus.ENQUIRY.value


def test_decline_enquiry(session):
    with TestClient(app) as client:
        payload = {
            "listing_id": str(uuid.uuid4()),
            "buyer_business_id": str(uuid.uuid4()),
            "seller_business_id": str(uuid.uuid4()),
            "quantity": "1.000",
            "unit": "kg",
            "unit_price": "3.0000",
        }
        create_resp = client.post("/api/v1/enquiries/", json=payload)
        enquiry_id = create_resp.json()["enquiry_id"]
        response = client.post(f"/api/v1/enquiries/{enquiry_id}/decline")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == EnquiryStatus.UNSUCCESSFUL.value
    assert data["failure_reason"] == FailureReason.DECLINED.value


def test_complete_enquiry(session):
    with TestClient(app) as client:
        payload = {
            "listing_id": str(uuid.uuid4()),
            "buyer_business_id": str(uuid.uuid4()),
            "seller_business_id": str(uuid.uuid4()),
            "quantity": "5.000",
            "unit": "kg",
            "unit_price": "4.0000",
        }
        create_resp = client.post("/api/v1/enquiries/", json=payload)
        enquiry_id = create_resp.json()["enquiry_id"]
        client.post(f"/api/v1/enquiries/{enquiry_id}/accept")
        response = client.post(f"/api/v1/enquiries/{enquiry_id}/complete")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == EnquiryStatus.COMPLETED.value
    assert data["closed_at"] is not None


def test_cancel_enquiry(session):
    with TestClient(app) as client:
        payload = {
            "listing_id": str(uuid.uuid4()),
            "buyer_business_id": str(uuid.uuid4()),
            "seller_business_id": str(uuid.uuid4()),
            "quantity": "5.000",
            "unit": "kg",
            "unit_price": "4.0000",
        }
        create_resp = client.post("/api/v1/enquiries/", json=payload)
        enquiry_id = create_resp.json()["enquiry_id"]
        response = client.post(f"/api/v1/enquiries/{enquiry_id}/cancel")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == EnquiryStatus.CANCELLED.value
    assert data["failure_reason"] == FailureReason.OTHER.value
    assert data["closed_at"] is not None


def test_start_payment_not_implemented(session):
    with TestClient(app) as client:
        payload = {
            "listing_id": str(uuid.uuid4()),
            "buyer_business_id": str(uuid.uuid4()),
            "seller_business_id": str(uuid.uuid4()),
            "quantity": "1.000",
            "unit": "kg",
            "unit_price": "1.0000",
        }
        create_resp = client.post("/api/v1/enquiries/", json=payload)
        enquiry_id = create_resp.json()["enquiry_id"]
        response = client.post(f"/api/v1/enquiries/{enquiry_id}/payments")
    assert response.status_code == 501
