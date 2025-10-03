# Create your views here.
import os
from rest_framework.decorators import api_view
from rest_framework.response import Response
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from payment.models import Payment, UnmatchedOfflinePayments
from payment.services import update_or_create_payment

@api_view(['POST'])
def handle_matching_payment(request):
    body = request.data or {}
    transactions = body.get('OfflineTransactions', []) or []

    for idx, tx in enumerate(transactions):
        try:
            status = (tx.get('status') or '').upper()
            if status != 'SUCCESS':
                continue

            amount_raw = tx.get('amount')
            try:
                amount = Decimal(str(amount_raw)) if amount_raw is not None else None
            except (InvalidOperation, TypeError):
                error_msg = f"Invalid amount: {amount_raw}"
                UnmatchedOfflinePayments.objects.create(
                    details=tx,
                    error_message=error_msg
                )
                continue

            created_at_str = tx.get('createdAt') or tx.get('updatedAt')
            received_date_str = date.today().strftime("%Y-%m-%d")
            if created_at_str:
                try:
                    try:
                        dt = datetime.strptime(created_at_str, "%Y-%m-%d %H:%M:%S.%f")
                    except ValueError:
                        dt = datetime.strptime(created_at_str, "%Y-%m-%d %H:%M:%S")
                    received_date_str = dt.date().strftime("%Y-%m-%d")
                except Exception:
                    pass
            matchingPaymentId = tx.get('matchingPaymentId')
            matchedPayment = Payment.objects.get(id=matchingPaymentId) if matchingPaymentId else None
            if not matchedPayment:
                error_msg = f"Matching payment not found: {matchingPaymentId}"
                UnmatchedOfflinePayments.objects.create(
                    details=tx,
                    error_message=error_msg
                )
                continue
            payload = {
                "uuid": matchedPayment.uuid if matchedPayment else None,
                "receipt_no": tx.get('orderId'),
                "origin": tx.get('paymentMethod'),
                "received_amount": str(amount) if amount is not None else None,
                "status": Payment.STATUS_POSTED,
                "received_date": received_date_str,
            }

            payment = update_or_create_payment(payload, request.user if hasattr(request, 'user') else payload)

        except Exception as exc:
            error_msg = str(exc)
            UnmatchedOfflinePayments.objects.create(
                details=tx,
                error_message=error_msg
            )

    return Response({
        "status": "ok"
    })
