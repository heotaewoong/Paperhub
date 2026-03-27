"""
PaperHub - AI 요약 Lambda
Bedrock Claude를 사용하여 논문 한줄요약 + 페이지요약 생성
"""
import json
import os
import boto3
from boto3.dynamodb.conditions import Key

bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')
papers_table = dynamodb.Table(os.environ['PAPERS_TABLE'])
pdf_bucket = os.environ['PDF_BUCKET']

MODEL_ID = 'amazon.nova-pro-v1:0'


def invoke_bedrock(prompt: str, max_tokens: int = 2048) -> str:
    """Bedrock Nova Pro 호출"""
    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        contentType='application/json',
        accept='application/json',
        body=json.dumps({
            'messages': [{'role': 'user', 'content': [{'text': prompt}]}],
            'inferenceConfig': {'maxTokens': max_tokens, 'temperature': 0.7},
        }),
    )
    result = json.loads(response['body'].read())
    return result['output']['message']['content'][0]['text']


def one_line_summary(title: str, abstract: str) -> str:
    """한줄 요약: Abstract → 1문장"""
    prompt = f"""다음 논문의 핵심 내용을 한국어 한 문장으로 요약해주세요.

제목: {title}
초록: {abstract}

한 문장 요약:"""
    return invoke_bedrock(prompt, max_tokens=200)


def page_summary(title: str, abstract: str) -> str:
    """페이지 요약: 전문 → 1페이지 분량"""
    prompt = f"""다음 논문을 한국어로 1페이지 분량으로 요약해주세요.
다음 구조로 작성해주세요:
1. 연구 배경 및 목적
2. 방법론
3. 주요 결과
4. 결론 및 시사점

제목: {title}
초록: {abstract}

요약:"""
    return invoke_bedrock(prompt, max_tokens=2048)


def bilingual_summary(title: str, abstract: str) -> list:
    """영어/한글 병렬 요약 - 문장 단위"""
    prompt = f"""다음 논문 초록을 문장 단위로 영어 원문과 한국어 번역을 병렬로 정리해주세요. JSON 배열로 응답하세요.
각 항목: {{"en": "영어 원문 문장", "ko": "한국어 번역"}}

초록: {abstract}

JSON 배열로만 응답:"""
    text = invoke_bedrock(prompt, max_tokens=3000)
    try:
        start = text.find('[')
        end = text.rfind(']') + 1
        return json.loads(text[start:end])
    except Exception:
        return []


def extract_keywords(title: str, abstract: str) -> list:
    """핵심 키워드 5개 추출"""
    prompt = f"""다음 논문에서 핵심 키워드 5개를 추출해주세요. JSON 배열로만 응답하세요.

제목: {title}
초록: {abstract}

["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"]"""
    text = invoke_bedrock(prompt, max_tokens=200)
    try:
        start = text.find('[')
        end = text.rfind(']') + 1
        return json.loads(text[start:end])
    except Exception:
        return []


def assess_difficulty(title: str, abstract: str) -> dict:
    """논문 난이도 평가"""
    prompt = f"""다음 논문의 난이도를 평가해주세요. JSON으로만 응답하세요.
- level: "입문", "중급", "고급" 중 하나
- reason: 한국어 한 문장으로 이유

제목: {title}
초록: {abstract}

{{"level": "...", "reason": "..."}}"""
    text = invoke_bedrock(prompt, max_tokens=200)
    try:
        start = text.find('{')
        end = text.rfind('}') + 1
        return json.loads(text[start:end])
    except Exception:
        return {"level": "중급", "reason": "판단 불가"}


def extract_vocab(title: str, abstract: str) -> list:
    """학술 단어장 자동 생성 - 제목+초록 전체 활용"""
    text_source = abstract if abstract and len(abstract) > 50 else title
    prompt = f"""다음 영어 논문의 제목과 초록에서 학술적으로 중요하고 어려운 영어 단어 10개를 추출해주세요.
일상적인 쉬운 단어(the, is, and 등)는 제외하고, 학술 논문에서 자주 사용되는 전문 용어와 고급 어휘를 선택해주세요.
각 항목을 JSON 배열로 응답하세요.
각 항목: {{"word": "영단어", "meaning": "한국어 뜻", "example": "논문에서 사용된 예문(영어 원문 그대로)", "pronunciation": "발음 기호"}}

제목: {title}
초록: {text_source}

JSON 배열로만 응답:"""
    text = invoke_bedrock(prompt, max_tokens=2500)
    try:
        start = text.find('[')
        end = text.rfind(']') + 1
        return json.loads(text[start:end])
    except Exception:
        return []


def analyze_sentences(abstract: str) -> list:
    """논문 문장 해부"""
    prompt = f"""다음 영어 논문 초록에서 가장 복잡한 문장 3개를 골라 구조 분석해주세요. JSON 배열로 응답하세요.
각 항목: {{"sentence": "원문 문장", "subject": "주어", "verb": "동사", "object": "목적어/보어", "literal": "직역(한국어)", "natural": "의역(한국어)", "explanation": "이 문장이 왜 이렇게 쓰였는지 한국어 설명"}}

초록: {abstract}

JSON 배열로만 응답:"""
    text = invoke_bedrock(prompt, max_tokens=2000)
    try:
        start = text.find('[')
        end = text.rfind(']') + 1
        return json.loads(text[start:end])
    except Exception:
        return []


def check_writing(original_abstract: str, user_writing: str) -> dict:
    """학술 영작 피드백 + 문법 교정 + 모범 답안"""
    prompt = f"""사용자가 논문 초록을 영어로 작성했습니다. 원문과 비교하여 피드백해주세요. JSON으로 응답하세요.

원문 초록: {original_abstract[:1000]}

사용자 작성: {user_writing}

{{"score": 0-100점수, "feedback": "한국어 전체 피드백", "model_answer": "이 논문 초록의 모범 영어 요약 (3-4문장)", "corrections": [{{"original": "사용자가 쓴 부분", "corrected": "교정된 표현", "reason": "이유"}}], "grammar_fixes": [{{"wrong": "문법 틀린 부분", "correct": "올바른 표현", "rule": "문법 규칙 설명(한국어)"}}], "good_points": ["잘한 점들"], "academic_tips": ["학술 영어 팁들"]}}}}"""
    text = invoke_bedrock(prompt, max_tokens=2000)
    try:
        start = text.find('{')
        end = text.rfind('}') + 1
        return json.loads(text[start:end])
    except Exception:
        return {"score": 0, "feedback": "피드백 생성 실패"}


def get_academic_patterns(section: str) -> list:
    """학술 표현 사전"""
    prompt = f"""학술 논문의 "{section}" 섹션에서 자주 사용되는 영어 표현 패턴 8개를 JSON 배열로 알려주세요.
각 항목: {{"pattern": "영어 표현 패턴", "meaning": "한국어 뜻", "example": "실제 논문에서 사용될 수 있는 예문", "usage_tip": "사용 팁(한국어)"}}

JSON 배열로만 응답:"""
    text = invoke_bedrock(prompt, max_tokens=2000)
    try:
        start = text.find('[')
        end = text.rfind(']') + 1
        return json.loads(text[start:end])
    except Exception:
        return []


def compare_papers(title1: str, abstract1: str, title2: str, abstract2: str) -> str:
    """두 논문 비교 분석"""
    prompt = f"""다음 두 논문을 비교 분석해주세요. 한국어로 작성하세요.

## 논문 A
제목: {title1}
초록: {abstract1}

## 논문 B
제목: {title2}
초록: {abstract2}

다음 항목으로 비교해주세요:
1. 연구 목적 비교
2. 방법론 비교
3. 주요 결과 비교
4. 강점과 한계점
5. 종합 평가"""
    return invoke_bedrock(prompt, max_tokens=2048)


def handler(event, context):
    """논문 요약 생성 - DB 조회 또는 직접 전달 모두 지원"""
    # paper_id 추출
    paper_id = ''
    if 'paperId' in event:
        paper_id = event['paperId']
    elif 'pathParameters' in event:
        paper_id = event.get('pathParameters', {}).get('id', '')

    # POST body에서 title/abstract 직접 받기 (실시간 검색 결과용)
    body = {}
    if event.get('body'):
        try:
            body = json.loads(event['body'])
        except Exception:
            body = {}

    title = body.get('title', '')
    abstract = body.get('abstract', '')
    summary_type = body.get('summaryType', event.get('summaryType', 'all'))

    # 논문 비교 모드
    if summary_type == 'compare':
        title2 = body.get('title2', '')
        abstract2 = body.get('abstract2', '')
        if not title2:
            return {'statusCode': 400, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'error': '비교할 두 번째 논문이 필요합니다'})}
        comparison = compare_papers(title, abstract, title2, abstract2)
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'comparison': comparison}, ensure_ascii=False)}

    # 영어학습: 단어장
    if summary_type == 'vocab':
        vocab = extract_vocab(title, abstract)
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'vocab': vocab}, ensure_ascii=False)}

    # 영어학습: 문장 해부
    if summary_type == 'sentences':
        sentences = analyze_sentences(abstract or title)
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'sentences': sentences}, ensure_ascii=False)}

    # 영어학습: 영작 피드백
    if summary_type == 'writing_check':
        user_writing = body.get('userWriting', '')
        result = check_writing(abstract, user_writing)
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps(result, ensure_ascii=False)}

    # 영어학습: 학술 표현 사전
    if summary_type == 'patterns':
        section = body.get('section', 'Introduction')
        patterns = get_academic_patterns(section)
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'patterns': patterns}, ensure_ascii=False)}

    # 영어학습: 영한 병렬 요약
    if summary_type == 'bilingual':
        pairs = bilingual_summary(title, abstract)
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'bilingual': pairs}, ensure_ascii=False)}

    # AI 논문 튜터 (Chat)
    if summary_type == 'chat':
        question = body.get('question', '')
        history = body.get('history', [])
        hist_text = '\n'.join([f"Q: {h.get('q','')}\nA: {h.get('a','')}" for h in history[-5:]])
        prompt = f"""당신은 논문 튜터입니다. 다음 논문에 대한 질문에 한국어로 답변해주세요.

제목: {title}
초록: {abstract}

{f'이전 대화:{chr(10)}{hist_text}{chr(10)}' if hist_text else ''}
질문: {question}

답변:"""
        answer = invoke_bedrock(prompt, max_tokens=1500)
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'answer': answer}, ensure_ascii=False)}

    # AI 연구 질문 생성
    if summary_type == 'research_questions':
        prompt = f"""다음 논문을 읽고 비판적 사고를 위한 연구 질문 5개를 생성해주세요. JSON 배열로 응답하세요.
각 항목: {{"question": "질문(한국어)", "type": "비판/확장/방법론/응용/한계 중 하나", "hint": "생각해볼 포인트(한국어)"}}

제목: {title}
초록: {abstract}

JSON 배열로만 응답:"""
        text = invoke_bedrock(prompt, max_tokens=1500)
        try:
            start = text.find('[')
            end = text.rfind(']') + 1
            questions = json.loads(text[start:end])
        except Exception:
            questions = []
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'questions': questions}, ensure_ascii=False)}

    # 논문 발표 슬라이드 생성
    if summary_type == 'slides':
        prompt = f"""다음 논문을 5장짜리 발표 슬라이드로 만들어주세요. JSON 배열로 응답하세요.
각 슬라이드: {{"title": "슬라이드 제목", "bullets": ["핵심 포인트 1", "핵심 포인트 2", "핵심 포인트 3"], "notes": "발표자 노트(한국어)"}}

슬라이드 구성:
1. 제목 슬라이드 (논문 제목, 저자, 발행일)
2. 연구 배경 및 목적
3. 방법론
4. 주요 결과
5. 결론 및 시사점

제목: {title}
초록: {abstract}

JSON 배열로만 응답:"""
        text = invoke_bedrock(prompt, max_tokens=2500)
        try:
            start = text.find('[')
            end = text.rfind(']') + 1
            slides = json.loads(text[start:end])
        except Exception:
            slides = []
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'slides': slides}, ensure_ascii=False)}

    # 영어+한국어 동시 요약
    if summary_type == 'bilingual_summary':
        en_prompt = f"""Summarize this paper in English with the following structure:

1. Background & Purpose
2. Methodology
3. Key Results
4. Conclusions & Implications

Title: {title}
Abstract: {abstract}

Please use the section headings above and write 2-3 sentences per section."""
        ko_prompt = f"""다음 논문을 한국어로 요약해주세요. 다음 구조로 작성해주세요:

1. 연구 배경 및 목적
2. 방법론
3. 주요 결과
4. 결론 및 시사점

제목: {title}
초록: {abstract}

각 섹션별 2-3문장으로 작성해주세요."""
        en_sum = invoke_bedrock(en_prompt, max_tokens=1000)
        ko_sum = invoke_bedrock(ko_prompt, max_tokens=1000)
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'enSummary': en_sum, 'koSummary': ko_sum}, ensure_ascii=False)}

    # 영어 퀴즈 생성
    if summary_type == 'quiz':
        prompt = f"""다음 논문 초록을 기반으로 영어 학습 퀴즈 5문제를 만들어주세요. JSON 배열로 응답하세요.
문제 유형을 섞어주세요: 빈칸 채우기, 문맥 추론, 내용 이해
각 항목: {{"type": "fill_blank/inference/comprehension", "question": "문제(영어)", "options": ["A", "B", "C", "D"], "answer": "정답 알파벳", "explanation": "해설(한국어)"}}

초록: {abstract}

JSON 배열로만 응답:"""
        text = invoke_bedrock(prompt, max_tokens=2500)
        try:
            start = text.find('[')
            end = text.rfind(']') + 1
            quiz = json.loads(text[start:end])
        except Exception:
            quiz = []
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'quiz': quiz}, ensure_ascii=False)}

    # 패러프레이징 연습
    if summary_type == 'paraphrase':
        prompt = f"""다음 논문 초록에서 핵심 문장 3개를 골라 패러프레이징 연습 문제를 만들어주세요. JSON 배열로 응답하세요.
각 항목: {{"original": "원문 문장", "paraphrased": "패러프레이징된 문장", "key_changes": "바뀐 핵심 표현들(한국어 설명)", "difficulty": "easy/medium/hard"}}

초록: {abstract}

JSON 배열로만 응답:"""
        text = invoke_bedrock(prompt, max_tokens=2000)
        try:
            start = text.find('[')
            end = text.rfind(']') + 1
            paraphrases = json.loads(text[start:end])
        except Exception:
            paraphrases = []
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'paraphrases': paraphrases}, ensure_ascii=False)}

    # 토론/발표 준비
    if summary_type == 'discussion':
        prompt = f"""다음 논문에 대한 학회 발표/토론 준비를 도와주세요. JSON으로 응답하세요.

제목: {title}
초록: {abstract}

{{"presentation_script": "2분 발표 스크립트(영어)", "expected_questions": [{{"question": "예상 질문(영어)", "answer_guide": "답변 가이드(영어)", "korean_tip": "한국어 팁"}}], "useful_expressions": [{{"expression": "유용한 영어 표현", "usage": "사용 상황(한국어)", "example": "예문"}}]}}"""
        text = invoke_bedrock(prompt, max_tokens=3000)
        try:
            start = text.find('{')
            end = text.rfind('}') + 1
            discussion = json.loads(text[start:end])
        except Exception:
            discussion = {}
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps(discussion, ensure_ascii=False)}

    # 번역 훈련
    if summary_type == 'translation_drill':
        prompt = f"""다음 논문 초록에서 핵심 표현 5개를 골라 한→영 번역 연습 문제를 만들어주세요. JSON 배열로 응답하세요.
각 항목: {{"korean": "한국어 표현", "english": "영어 정답", "hint": "힌트(첫 글자 또는 키워드)", "context": "논문에서 사용된 문맥"}}

초록: {abstract}

JSON 배열로만 응답:"""
        text = invoke_bedrock(prompt, max_tokens=1500)
        try:
            start = text.find('[')
            end = text.rfind(']') + 1
            drills = json.loads(text[start:end])
        except Exception:
            drills = []
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'drills': drills}, ensure_ascii=False)}

    # body에 title/abstract가 없으면 DB에서 조회
    if not title and paper_id:
        result = papers_table.query(
            KeyConditionExpression=Key('paperId').eq(paper_id),
        )
        items = result.get('Items', [])
        if items:
            title = items[0].get('title', '')
            abstract = items[0].get('abstract', '')

    if not title and not abstract:
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': '논문 제목 또는 초록이 필요합니다'}),
        }

    response = {'paperId': paper_id}

    if summary_type in ('oneline', 'all'):
        response['oneLineSummary'] = one_line_summary(title, abstract)

    if summary_type in ('page', 'all'):
        response['pageSummary'] = page_summary(title, abstract)

    # 항상 키워드 + 난이도 추가
    try:
        response['keywords'] = extract_keywords(title, abstract)
    except Exception:
        response['keywords'] = []
    try:
        response['difficulty'] = assess_difficulty(title, abstract)
    except Exception:
        response['difficulty'] = {"level": "중급", "reason": ""}

    # DB에 있는 논문이면 요약 결과 저장
    if paper_id and not paper_id.startswith(('arxiv-', 'ss-')):
        try:
            update_expr = 'SET '
            expr_values = {}
            if 'oneLineSummary' in response:
                update_expr += 'oneLineSummary = :ols, '
                expr_values[':ols'] = response['oneLineSummary']
            if 'pageSummary' in response:
                update_expr += 'pageSummary = :ps, '
                expr_values[':ps'] = response['pageSummary']
            update_expr = update_expr.rstrip(', ')
            if expr_values:
                papers_table.update_item(
                    Key={'paperId': paper_id, 'source': 'pubmed'},
                    UpdateExpression=update_expr,
                    ExpressionAttributeValues=expr_values,
                )
        except Exception:
            pass  # 저장 실패해도 요약 결과는 반환

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(response, ensure_ascii=False),
    }
