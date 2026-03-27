"""
PaperHub - AI 추천 Lambda
읽은 논문 기반으로 유사 논문 추천
"""
import json
import os
import boto3
from boto3.dynamodb.conditions import Key

bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
dynamodb = boto3.resource('dynamodb')
papers_table = dynamodb.Table(os.environ['PAPERS_TABLE'])
bookmarks_table = dynamodb.Table(os.environ['BOOKMARKS_TABLE'])

MODEL_ID = 'amazon.nova-pro-v1:0'


def get_user_papers(user_id: str) -> list:
    """사용자가 북마크한 논문 목록 조회"""
    result = bookmarks_table.query(
        KeyConditionExpression=Key('userId').eq(user_id),
    )
    paper_ids = [item['paperId'] for item in result.get('Items', [])]
    papers = []
    for pid in paper_ids[:10]:  # 최근 10개만
        r = papers_table.query(KeyConditionExpression=Key('paperId').eq(pid))
        if r['Items']:
            papers.append(r['Items'][0])
    return papers


def get_candidate_papers(category: str, exclude_ids: set) -> list:
    """추천 후보 논문 조회"""
    result = papers_table.query(
        IndexName='by-category',
        KeyConditionExpression=Key('category').eq(category),
        ScanIndexForward=False,
        Limit=50,
    )
    return [p for p in result['Items'] if p['paperId'] not in exclude_ids]


def rank_with_ai(user_papers: list, candidates: list) -> list:
    """AI로 추천 논문 랭킹"""
    user_titles = [p.get('title', '') for p in user_papers]
    candidate_info = [
        {'id': p['paperId'], 'title': p.get('title', ''), 'abstract': p.get('abstract', '')[:200]}
        for p in candidates[:20]
    ]

    prompt = f"""사용자가 읽은 논문 제목들:
{json.dumps(user_titles, ensure_ascii=False)}

후보 논문들:
{json.dumps(candidate_info, ensure_ascii=False)}

사용자의 관심사에 가장 적합한 논문 5개를 선택하고, 각각에 대해 추천 이유를 한국어로 간단히 설명해주세요.
JSON 배열로 응답해주세요: [{{"id": "...", "reason": "..."}}]"""

    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        contentType='application/json',
        accept='application/json',
        body=json.dumps({
            'messages': [{'role': 'user', 'content': [{'text': prompt}]}],
            'inferenceConfig': {'maxTokens': 1024, 'temperature': 0.7},
        }),
    )
    result = json.loads(response['body'].read())
    text = result['output']['message']['content'][0]['text']

    try:
        # JSON 파싱 시도
        start = text.find('[')
        end = text.rfind(']') + 1
        return json.loads(text[start:end])
    except (json.JSONDecodeError, ValueError):
        return []


def handler(event, context):
    """논문 추천"""
    if 'pathParameters' in event:
        paper_id = event['pathParameters'].get('id', '')
        params = event.get('queryStringParameters') or {}
        user_id = params.get('userId', 'default-user')
    else:
        paper_id = event.get('paperId', '')
        user_id = event.get('userId', 'default-user')

    # 사용자 논문 가져오기
    user_papers = get_user_papers(user_id)

    # 현재 논문 정보도 추가
    if paper_id:
        r = papers_table.query(KeyConditionExpression=Key('paperId').eq(paper_id))
        if r['Items']:
            user_papers.append(r['Items'][0])

    if not user_papers:
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'recommendations': [], 'message': '북마크한 논문이 없어 추천할 수 없습니다'}),
        }

    # 카테고리별 후보 수집
    exclude_ids = {p['paperId'] for p in user_papers}
    categories = list({p.get('category', '') for p in user_papers if p.get('category')})
    candidates = []
    for cat in categories:
        candidates.extend(get_candidate_papers(cat, exclude_ids))

    # AI 랭킹
    recommendations = rank_with_ai(user_papers, candidates)

    # 추천 논문 상세 정보 추가
    enriched = []
    for rec in recommendations:
        r = papers_table.query(KeyConditionExpression=Key('paperId').eq(rec['id']))
        if r['Items']:
            item = r['Items'][0]
            item['recommendReason'] = rec.get('reason', '')
            enriched.append(item)

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
        'body': json.dumps({'recommendations': enriched}, ensure_ascii=False, default=str),
    }
