from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError, PermissionDenied
from payment.apps import PaymentConfig
from payment.models import Payment, PaymentMutation
from policy import models as policy_models
from payment.services import update_or_create_payment, detach_payment_detail, set_payment_deleted, \
    update_or_create_payment_detail, PaymentIdReservationService
from typing import Optional
from core.models import MutationLog, Language

import graphene
from core.schema import OpenIMISMutation
from django.utils.translation import gettext_lazy, gettext as _
from django.middleware.csrf import CsrfViewMiddleware
from core.utils import is_this_session_superuser
from django.contrib.auth.models import AnonymousUser
from django.utils import translation
from core.schema import (
    OpenIMISMutation,
    OpenIMISJSONEncoder,
    signal_mutation,
    signal_mutation_module_validate,
    signal_mutation_module_before_mutating,
    signal_mutation_module_after_mutating,
)
from django.conf import settings
import json
class PaymentBase:
    id = graphene.Int(required=False, read_only=True)
    uuid = graphene.String(required=False)
    expected_amount = graphene.Decimal(max_digits=18, decimal_places=2, required=False)
    received_amount = graphene.Decimal(max_digits=18, decimal_places=2, required=False)
    officer_code = graphene.String(required=False)
    phone_number = graphene.String(required=False)
    request_date = graphene.Date(required=False)
    received_date = graphene.Date(required=False)
    status = graphene.Int(required=False)
    transaction_no = graphene.String(required=False)
    origin = graphene.String(required=False)
    matched_date = graphene.Date(required=False)
    receipt_no = graphene.String(required=False)
    payment_date = graphene.Date(required=False)
    rejected_reason = graphene.String(required=False)
    date_last_sms = graphene.Date(required=False)
    language_name = graphene.String(required=False)
    type_of_payment = graphene.String(required=False)
    transfer_fee = graphene.Decimal(max_digits=18, decimal_places=2, required=False)
    premium_uuid = graphene.String(
        required=False, description=gettext_lazy("payment.gql.payment_base.premium_uuid"))
    reserved_payment_id = graphene.Int(required=False, description="Use a pre-reserved paymentid for creation")


class CreatePaymentMutation(OpenIMISMutation):
    """
    Create a payment for policy with or without a payer
    """
    _mutation_module = "payment"
    _mutation_class = "CreatePaymentMutation"

    class Input(PaymentBase, OpenIMISMutation.Input):
        pass

    @classmethod
    def async_mutate(cls, user, **data) -> Optional[str]:
        try:
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(
                    _("mutation.authentication_required"))
            if not user.has_perms(PaymentConfig.gql_mutation_create_payments_perms):
                raise PermissionDenied(_("unauthorized"))
            premium_uuid = data.pop("premium_uuid") if "premium_uuid" in data else None
            client_mutation_id = data.get("client_mutation_id")
            payment = update_or_create_payment(data, user)
            if premium_uuid:
                update_or_create_payment_detail(payment, premium_uuid, user)
            PaymentMutation.object_mutated(user, client_mutation_id=client_mutation_id, payment=payment)
            return None
        except Exception as exc:
            return [{
                'message': _("payment.mutation.failed_to_create_payment"),
                'detail': str(exc)}
            ]


class UpdatePaymentMutation(OpenIMISMutation):
    """
    Update a payment for policy
    """
    _mutation_module = "payment"
    _mutation_class = "UpdatePaymentMutation"

    class Input(PaymentBase, OpenIMISMutation.Input):
        pass

    @classmethod
    def async_mutate(cls, user, **data) -> Optional[str]:
        try:
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(
                    _("mutation.authentication_required"))
            if not user.has_perms(PaymentConfig.gql_mutation_update_payments_perms):
                raise PermissionDenied(_("unauthorized"))
            premium_uuid = data.pop("premium_uuid") if "premium_uuid" in data else None
            payment = update_or_create_payment(data, user)
            if premium_uuid:
                update_or_create_payment_detail(payment, premium_uuid, user)
            return None
        except Exception as exc:
            return [{
                'message': _("payment.mutation.failed_to_update_payment") %
                           {'id': data.get('id') if data else None},
                'detail': str(exc)}
            ]


class DeletePaymentsMutation(OpenIMISMutation):
    """
    Delete one or several Payments.
    """
    _mutation_module = "payment"
    _mutation_class = "DeletePaymentsMutation"

    class Input(OpenIMISMutation.Input):
        uuids = graphene.List(graphene.String)

    @classmethod
    def async_mutate(cls, user, **data):
        if not user.has_perms(PaymentConfig.gql_mutation_delete_payments_perms):
            raise PermissionDenied(_("unauthorized"))
        errors = []
        for payment_uuid in data["uuids"]:
            payment = Payment.objects \
                .filter(uuid=payment_uuid) \
                .first()
            if payment is None:
                errors.append({
                    'title': payment_uuid,
                    'list': [{'message': _(
                        "payment.validation.id_does_not_exist") % {'id': payment_uuid}}]
                })
                continue
            errors += set_payment_deleted(payment)
        if len(errors) == 1:
            errors = errors[0]['list']
        return errors
class ReservePaymentIdsMutation(OpenIMISMutation):
    _mutation_module = "payment"
    _mutation_class = "ReservePaymentIdsMutation"

    class Input(OpenIMISMutation.Input):
        amount = graphene.Int(required=True)
        autogenerate = graphene.Boolean(required=False)

    reserved_chf_ids = graphene.List(graphene.String)

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(_("mutation.authentication_required"))
            if not user.has_perms(PaymentConfig.gql_mutation_create_payments_perms):
                raise PermissionDenied(_("unauthorized"))
            amount = int(data.get('amount') or 0)
            reserved = PaymentIdReservationService(user).reserve_new(amount)
            if data.get('autogenerate', False):
                return { 'reserved_chf_ids': reserved }
            return None
        except Exception as exc:
            return [{
                'message': _("insuree.mutation.failed_to_reserve_ids"),
                'detail': str(exc)}
            ]

    @classmethod
    def mutate_and_get_payload(cls, root, info, **data):
        request = getattr(info, "context", None)

        user_agent = request.headers.get("User-Agent", "")
        current_session_key = request.session.session_key
        if not is_this_session_superuser(current_session_key):
            if not any(bypass in user_agent for bypass in getattr(settings, "USER_AGENT_CSRF_BYPASS", [])):
                csrf_middleware = CsrfViewMiddleware(lambda req: None)
                reason = csrf_middleware.process_view(request, None, (), {})
                if reason:
                    raise PermissionDenied("CSRF token missing or incorrect.")

        mutation_log = MutationLog.objects.create(
            json_content=json.dumps(data, cls=OpenIMISJSONEncoder),
            user_id=info.context.user.id if info.context.user else None,
            client_mutation_id=data.get("client_mutation_id"),
            client_mutation_label=data.get("client_mutation_label"),
            client_mutation_details=json.dumps(
                data.get("client_mutation_details"), cls=OpenIMISJSONEncoder
            )
            if data.get("client_mutation_details")
            else None,
        )
        if (
            info
            and info.context
            and info.context.user
            and not info.context.user.is_anonymous
        ):
            lang = info.context.user.language
            if isinstance(lang, Language):
                translation.activate(lang.code)
            else:
                translation.activate(lang)

        error_messages = None
        generated_fields = {}
        try:
            results = signal_mutation.send(
                sender=cls,
                mutation_log_id=mutation_log.id,
                data=data,
                user=info.context.user,
                mutation_module=cls._mutation_module,
                mutation_class=cls.__name__,
            )
            results.extend(
                signal_mutation_module_validate[cls._mutation_module].send(
                    sender=cls,
                    mutation_log_id=mutation_log.id,
                    data=data,
                    user=info.context.user,
                    mutation_module=cls._mutation_module,
                    mutation_class=cls.__name__,
                )
            )
            errors = [err for r in results for err in r[1]]
            if errors:
                mutation_log.mark_as_failed(json.dumps(errors))
                return cls(internal_id=mutation_log.id)

            signal_mutation_module_before_mutating[cls._mutation_module].send(
                sender=cls, mutation_log_id=mutation_log.id, data=data, user=info.context.user,
                mutation_module=cls._mutation_module, mutation_class=cls.__name__
            )
            try:
                from core.schema import OpenIMISJSONEncoder as _Encoder
                mutation_data = cls.coerce_mutation_data(json.loads(
                    json.dumps(data, cls=_Encoder)))
                mutation_data.pop("mutation_extensions", None)
                messages = cls.async_mutate(
                    info.context.user if info.context and info.context.user else None,
                    **mutation_data)
                if mutation_data.get('autogenerate', False) and isinstance(messages, dict):
                    # capture generated fields for response
                    generated_fields.update(messages)
                    error_messages = None
                else:
                    error_messages = messages
                if not error_messages:
                    mutation_log.mark_as_successful()
                else:
                    exceptions = [message.pop("exc") for message in error_messages if "exc" in message]
                    errors_json = json.dumps(error_messages)
                    mutation_log.mark_as_failed(errors_json)
            except BaseException as exc:
                error_messages = exc
                mutation_log.mark_as_failed(f"The mutation threw a {type(exc)}, check logs for details")
            signal_mutation_module_after_mutating[cls._mutation_module].send(
                sender=cls, mutation_log_id=mutation_log.id, data=data, user=info.context.user,
                mutation_module=cls._mutation_module, mutation_class=cls.__name__,
                error_messages=error_messages
            )
        except Exception as exc:
            mutation_log.mark_as_failed(exc)

        instance = cls(internal_id=mutation_log.id)
        if generated_fields.get('reserved_chf_ids') is not None:
            setattr(instance, 'reserved_chf_ids', generated_fields.get('reserved_chf_ids'))
        return instance

def on_policy_mutation(sender, **kwargs):
    errors = []
    if kwargs.get("mutation_class") == 'DeletePoliciesMutation':
        uuids = kwargs['data'].get('uuids', [])
        policies = policy_models.Policy.objects.prefetch_related("premiums__payment_details").filter(uuid__in=uuids).all()
        for policy in policies:
            for premium in policy.premiums.all():
                for payment_detail in premium.payment_details.all():
                    errors += detach_payment_detail(payment_detail)
    return errors


def on_payment_mutation(sender, **kwargs):
    uuids = kwargs['data'].get('uuids', [])
    if not uuids:
        uuid = kwargs['data'].get('uuid', None)
        uuids = [uuid] if uuid else []
    if not uuids:
        return []
    impacted_payments = Payment.objects.filter(uuid__in=uuids).all()
    for payment in impacted_payments:
        PaymentMutation.objects.get_or_create(payment=payment, mutation_id=kwargs['mutation_log_id'])
    return []
