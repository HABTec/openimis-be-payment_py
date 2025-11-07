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
    body = {k.lower(): v for k, v in body.items()}
    transactions = body.get('offlinetransactions', []) or []
    transactions = [{k.lower(): v.lower() for k, v in obj.items()} for obj in transactions]
    for idx, tx in enumerate(transactions):
        try:
            status = (tx.get('status') or '')
            if status != 'success':
                continue

            amount_raw = tx.get('amount')
            receipt_no = tx.get('orderid')
            try:
                amount = Decimal(str(amount_raw)) if amount_raw is not None else None
            except (InvalidOperation, TypeError):
                error_msg = f"Invalid amount: {amount_raw}"
                UnmatchedOfflinePayments.objects.create(
                    details=tx,
                    error_message=error_msg
                )
                continue

            created_at_str = tx.get('createdat') or tx.get('updatedat')
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
            matchingPaymentId = tx.get('matchingpaymentid')
            if matchingPaymentId:
                matchedPayment = Payment.objects.get(id=matchingPaymentId)
            elif amount and receipt_no:
                matchedPayment = Payment.objects.filter(
                    receipt_no=receipt_no,
                )
            if not matchedPayment:
                error_msg = f"Matching payment not found: {matchingPaymentId if matchingPaymentId else receipt_no}"
                UnmatchedOfflinePayments.objects.create(
                    details=tx,
                    error_message=error_msg
                )
                continue
            payload = {
                "uuid": matchedPayment[0].uuid if matchedPayment else None,
                "receipt_no": receipt_no,
                "origin": tx.get('paymentmethod'),
                "received_amount": str(amount) if amount is not None else None,
                "status": Payment.STATUS_PAYMENTMATCHED,
                "received_date": received_date_str,
            }

            payment = update_or_create_payment(payload, request.user if hasattr(request, 'user') else payload , matching=True)

        except Exception as exc:
            error_msg = str(exc)
            UnmatchedOfflinePayments.objects.create(
                details=tx,
                error_message=error_msg
            )

    return Response({
        "status": "ok"
    })
