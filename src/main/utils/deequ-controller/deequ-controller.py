# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import sys
import time
import logging

from botocore.exceptions import ClientError
import boto3
from boto3.dynamodb.conditions import Key, Attr
from awsglue.utils import getResolvedOptions

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
glue = boto3.client('glue')
ssm = boto3.client('ssm')


def get_table_suffix(environment):
    try:
        appsync_api_id = ssm.get_parameter(
            Name=f"/DataQuality/{environment}/AppSync/GraphQLApi")['Parameter']['Value']
        return f"{appsync_api_id}-{env}"
    except ClientError as e:
        if e.response['Error']['Code'] == 'ParameterNotFound':
            return f"{env}"
        else:
            raise e


def get_suggestions(table, key_value):
    response = table.query(
        IndexName='table-index',
        KeyConditionExpression=Key('tableHashKey').eq(key_value)
    )
    return response['Items']


def testGlueJob(jobId, count, sec, jobName):
    i = 0
    while i < count:
        response = glue.get_job_run(JobName=jobName, RunId=jobId)
        status = response['JobRun']['JobRunState']
        if status == 'SUCCEEDED':
            return 1
        elif (status == 'RUNNING' or status == 'STARTING' or status == 'STOPPING'):
            time.sleep(sec)
            i += 1
        else:
            return 0
        if i == count:
            return 0


# Required Parameters
args = getResolvedOptions(sys.argv, [
    'env',
    'glueSuggestionVerificationJob',
    'glueVerificationJob',
    'glueProfilerJob',
    'glueDatabase',
    'glueTables',
    'pushDownPredicate'
])

env = args['env']
table_suffix = get_table_suffix(env)
suggestion_dynamodb_table_name = f"DataQualitySuggestion-{table_suffix}"
analysis_dynamodb_table_name = f"DataQualityAnalyzer-{table_suffix}"
suggestions_job_name = args['glueSuggestionVerificationJob']
verification_job_name = args['glueVerificationJob']
profile_job_name = args['glueProfilerJob']
glue_database = args['glueDatabase']
glue_tables = [x.strip() for x in args['glueTables'].split(',')]
pushDownPredicate = args['pushDownPredicate']
pradicate = [x.strip() for x in args['pushDownPredicate'].split(',')]

mapTablePredicate = dict(zip(glue_tables,pradicate))
#print(mapTablePredicate)
# Determine which tables had Deequ data quality suggestions set up already
suggestions_tables = []
verification_tables = []
pradicate_tables=[]
suggestions_dynamo = dynamodb.Table(suggestion_dynamodb_table_name)
for table in glue_tables:
    suggestions_item = get_suggestions(
        suggestions_dynamo, f"{glue_database}-{table}")
    if suggestions_item:
        verification_tables.append(table)
    else:
        suggestions_tables.append(table)
        pradicate_tables.append(mapTablePredicate.get(table))
        #print(pradicate_tables)

logger.info('Calling Glue Jobs')
logger.info('Job 1 :suggestions_job_name')

#data-quality-suggestion-analysis-verification-runner
if suggestions_tables:
    suggestions_response = glue.start_job_run(
        JobName=suggestions_job_name,
        Arguments={
            '--dynamodbSuggestionTableName': suggestion_dynamodb_table_name,
            '--dynamodbAnalysisTableName': analysis_dynamodb_table_name,
            '--glueDatabase': glue_database,
            '--glueTables': ','.join(suggestions_tables),
            '--pushDownPredicate': pushDownPredicate,
            '--mapTablePredicate': ','.join(pradicate_tables) 

        }
    )

logger.info('Job 2 :verification_job_name')
#data-quality-analysis-verification-runner
if verification_tables:
    verification_response = glue.start_job_run(
        JobName=verification_job_name,
        Arguments={
            '--dynamodbSuggestionTableName': suggestion_dynamodb_table_name,
            '--dynamodbAnalysisTableName': analysis_dynamodb_table_name,
            '--glueDatabase': glue_database,
            '--glueTables': ','.join(verification_tables),
            '--pushDownPredicate': pushDownPredicate

        }
    )

logger.info('Job 3 :profile_job_name')
#data-quality-profile-runner
profile_response = glue.start_job_run(
    JobName=profile_job_name,
    Arguments={
        '--glueDatabase': glue_database,
        '--glueTables': ','.join(glue_tables),
        '--pushDownPredicate': pushDownPredicate

    }
)
logger.info('profile_job_name:pushDownPredicate='+pushDownPredicate)

# Wait for execution to complete, timeout in 60*30=1800 secs
logger.info('Waiting for execution')
message = 'Error during Controller execution - Check logs'
if suggestions_tables:
    if testGlueJob(suggestions_response['JobRunId'], 60, 30, suggestions_job_name) != 1:
        raise ValueError(message)
if verification_tables:
    if testGlueJob(verification_response['JobRunId'], 60, 30, verification_job_name) != 1:
        raise ValueError(message)
if testGlueJob(profile_response['JobRunId'], 60, 30, profile_job_name) != 1:
    raise ValueError(message)
