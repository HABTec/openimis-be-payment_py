import base64
from unittest import mock
from django.test import TestCase

import graphene
from contract.tests.helpers import *
from contract.models import Contract, ContractDetails
from core.models import TechnicalUser
from core.models.openimis_graphql_test_case import openIMISGraphQLTestCase, BaseTestContext
from core.test_helpers import create_test_interactive_user
from policyholder.tests.helpers import *
from contribution_plan.tests.helpers import create_test_contribution_plan, \
    create_test_contribution_plan_bundle, create_test_contribution_plan_bundle_details
from payment import schema as payment_schema
from graphene import Schema
from graphene.test import Client
from graphene_django.utils.testing import GraphQLTestCase
from django.conf import settings
import json
import uuid
from graphql_jwt.shortcuts import get_token
from calcrule_contribution_legacy.calculation_rule import ContributionPlanCalculationRuleProductModeling

class QueryTestContract(openIMISGraphQLTestCase):
    # This is required by some version of graphene but is never used. It should be set to the schema but the import
    # is shown as an error in the IDE, so leaving it as True.
    GRAPHQL_SCHEMA = True
    admin_user = None
    schema = Schema(
            query=payment_schema.Query,
    )


    class AnonymousUserContext:
        user = mock.Mock(is_anonymous=True)

    @classmethod
    def setUpClass(cls):
        super(QueryTestContract, cls).setUpClass()
        cls.user = User.objects.filter(username='admin', i_user__isnull=False).first()
        if not cls.user:
            cls.user=create_test_interactive_user(username='admin')
        # some test data so as to created contract properly
        cls.user_token = BaseTestContext(user=cls.user).get_jwt()
        
    def test_query_payment_additionnal_filter(self):
        response = self.query(
            """
    query {
      payments(additionalFilter: "{\\"contract\\":\\"5b358ead-f2fb-4acf-ba90-3c1c74e0bf01\\"}",first: 10,orderBy: ["-receivedDate"])
      {
        totalCount
        
    pageInfo { hasNextPage, hasPreviousPage, startCursor, endCursor}
    edges
    {
      node
      {
        uuid,id,requestDate,expectedAmount,receivedDate,receivedAmount,status,receiptNo,typeOfPayment,clientMutationId,validityTo
      }
    }
      }
    }
    """,
            headers={"HTTP_AUTHORIZATION": f"Bearer {self.user_token}"})
        self.assertResponseNoErrors(response)

