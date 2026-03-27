import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as elasticache from 'aws-cdk-lib/aws-elasticache';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';

export class PaperhubStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ========== S3 Buckets ==========
    // PDF 캐시 저장소
    const pdfBucket = new s3.Bucket(this, 'PdfCacheBucket', {
      bucketName: `paperhub-pdf-cache-${this.account}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      lifecycleRules: [{ expiration: cdk.Duration.days(30) }],
    });

    // 프론트엔드 호스팅 버킷
    const frontendBucket = new s3.Bucket(this, 'FrontendBucket', {
      bucketName: `paperhub-frontend-${this.account}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
    });

    // ========== DynamoDB ==========
    // 논문 메타데이터 테이블
    const papersTable = new dynamodb.Table(this, 'PapersTable', {
      tableName: 'paperhub-papers',
      partitionKey: { name: 'paperId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'source', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    papersTable.addGlobalSecondaryIndex({
      indexName: 'by-category',
      partitionKey: { name: 'category', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'publishedDate', type: dynamodb.AttributeType.STRING },
    });

    // 북마크 테이블
    const bookmarksTable = new dynamodb.Table(this, 'BookmarksTable', {
      tableName: 'paperhub-bookmarks',
      partitionKey: { name: 'userId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'paperId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ========== Lambda Functions ==========
    // 논문 수집 Lambda
    const ingestFn = new lambda.Function(this, 'IngestFunction', {
      functionName: 'paperhub-ingest',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset('lambda/ingest'),
      timeout: cdk.Duration.minutes(10),
      memorySize: 512,
      environment: {
        PAPERS_TABLE: papersTable.tableName,
        PDF_BUCKET: pdfBucket.bucketName,
      },
    });

    // 서빙 Lambda (API)
    const serveFn = new lambda.Function(this, 'ServeFunction', {
      functionName: 'paperhub-serve',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset('lambda/serve'),
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      environment: {
        PAPERS_TABLE: papersTable.tableName,
        BOOKMARKS_TABLE: bookmarksTable.tableName,
        PDF_BUCKET: pdfBucket.bucketName,
      },
    });

    // AI 요약 Lambda
    const summarizeFn = new lambda.Function(this, 'SummarizeFunction', {
      functionName: 'paperhub-summarize',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset('lambda/ai-summarize'),
      timeout: cdk.Duration.minutes(5),
      memorySize: 1024,
      environment: {
        PAPERS_TABLE: papersTable.tableName,
        PDF_BUCKET: pdfBucket.bucketName,
      },
    });

    // AI 추천 Lambda
    const recommendFn = new lambda.Function(this, 'RecommendFunction', {
      functionName: 'paperhub-recommend',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset('lambda/ai-recommend'),
      timeout: cdk.Duration.minutes(2),
      memorySize: 512,
      environment: {
        PAPERS_TABLE: papersTable.tableName,
        BOOKMARKS_TABLE: bookmarksTable.tableName,
      },
    });

    // Lambda 권한 부여
    papersTable.grantReadWriteData(ingestFn);
    papersTable.grantReadData(serveFn);
    papersTable.grantReadWriteData(summarizeFn);
    papersTable.grantReadData(recommendFn);
    bookmarksTable.grantReadWriteData(serveFn);
    bookmarksTable.grantReadData(recommendFn);
    pdfBucket.grantReadWrite(ingestFn);
    pdfBucket.grantRead(serveFn);
    pdfBucket.grantRead(summarizeFn);

    // Bedrock 권한
    const bedrockPolicy = new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel'],
      resources: ['*'],
    });
    summarizeFn.addToRolePolicy(bedrockPolicy);
    recommendFn.addToRolePolicy(bedrockPolicy);

    // ========== Step Functions (AI 워크플로우) ==========
    const summarizeTask = new tasks.LambdaInvoke(this, 'SummarizeTask', {
      lambdaFunction: summarizeFn,
      outputPath: '$.Payload',
    });

    const recommendTask = new tasks.LambdaInvoke(this, 'RecommendTask', {
      lambdaFunction: recommendFn,
      outputPath: '$.Payload',
    });

    // 병렬 처리: 한줄요약 + 페이지요약 + 추천논문
    const aiParallel = new sfn.Parallel(this, 'AIParallelProcessing')
      .branch(summarizeTask)
      .branch(recommendTask);

    const aiWorkflow = new sfn.StateMachine(this, 'AIWorkflow', {
      stateMachineName: 'paperhub-ai-workflow',
      definitionBody: sfn.DefinitionBody.fromChainable(aiParallel),
      timeout: cdk.Duration.minutes(10),
    });

    // ========== EventBridge (주기적 수집) ==========
    new events.Rule(this, 'IngestSchedule', {
      ruleName: 'paperhub-ingest-schedule',
      schedule: events.Schedule.rate(cdk.Duration.hours(6)),
      targets: [new targets.LambdaFunction(ingestFn)],
    });

    // ========== API Gateway ==========
    const api = new apigateway.RestApi(this, 'PaperhubApi', {
      restApiName: 'paperhub-api',
      deployOptions: { stageName: 'prod' },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
      },
    });

    // /papers
    const papers = api.root.addResource('papers');
    papers.addMethod('GET', new apigateway.LambdaIntegration(serveFn));

    // /papers/{id}
    const paper = papers.addResource('{id}');
    paper.addMethod('GET', new apigateway.LambdaIntegration(serveFn));

    // /papers/{id}/summarize
    const summarize = paper.addResource('summarize');
    summarize.addMethod('POST', new apigateway.LambdaIntegration(summarizeFn));

    // /papers/{id}/recommend
    const recommend = paper.addResource('recommend');
    recommend.addMethod('GET', new apigateway.LambdaIntegration(recommendFn));

    // /search (실시간 멀티소스 검색)
    const search = api.root.addResource('search');
    search.addMethod('GET', new apigateway.LambdaIntegration(serveFn));

    // /trends (연구 트렌드)
    const trends = api.root.addResource('trends');
    trends.addMethod('GET', new apigateway.LambdaIntegration(serveFn));

    // /citations (인용 논문)
    const citations = api.root.addResource('citations');
    citations.addMethod('GET', new apigateway.LambdaIntegration(serveFn));

    // /bookmarks
    const bookmarks = api.root.addResource('bookmarks');
    bookmarks.addMethod('GET', new apigateway.LambdaIntegration(serveFn));
    bookmarks.addMethod('POST', new apigateway.LambdaIntegration(serveFn));

    // /bookmarks/{paperId}
    const bookmark = bookmarks.addResource('{paperId}');
    bookmark.addMethod('DELETE', new apigateway.LambdaIntegration(serveFn));

    // ========== CloudFront ==========
    const distribution = new cloudfront.Distribution(this, 'PaperhubCDN', {
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(frontendBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
      },
      additionalBehaviors: {
        '/api/*': {
          origin: new origins.RestApiOrigin(api),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
      },
      defaultRootObject: 'index.html',
      errorResponses: [
        { httpStatus: 404, responseHttpStatus: 200, responsePagePath: '/index.html' },
      ],
    });

    // ========== Outputs ==========
    new cdk.CfnOutput(this, 'CloudFrontURL', { value: `https://${distribution.distributionDomainName}` });
    new cdk.CfnOutput(this, 'ApiURL', { value: api.url });
    new cdk.CfnOutput(this, 'PdfBucketName', { value: pdfBucket.bucketName });
  }
}
