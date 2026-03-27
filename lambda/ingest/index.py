"""
PaperHub - 논문 수집 Lambda
PubMed API에서 논문 메타데이터를 수집하고 DynamoDB에 저장
"""
import json
import os
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')
papers_table = dynamodb.Table(os.environ['PAPERS_TABLE'])
pdf_bucket = os.environ['PDF_BUCKET']

PUBMED_SEARCH_URL = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi'
PUBMED_FETCH_URL = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi'

# 수집할 카테고리 키워드 (전 분야)
CATEGORIES = [
    # AI / CS
    'machine learning',
    'deep learning',
    'natural language processing',
    'computer vision',
    'reinforcement learning',
    'large language model',
    'generative AI',
    'robotics',
    'cybersecurity',
    # 바이오 / 의학
    'genomics',
    'proteomics',
    'drug discovery',
    'clinical trial',
    'cancer research',
    'neuroscience',
    'immunology',
    'epidemiology',
    'biomedical imaging',
    'precision medicine',
    # 물리 / 수학 / 공학
    'quantum computing',
    'materials science',
    'renewable energy',
    'semiconductor',
    'signal processing',
    # 환경 / 사회
    'climate change',
    'sustainability',
    'public health',
    'economics',
    'psychology',
]


def search_pubmed(query: str, max_results: int = 20) -> list:
    """PubMed에서 논문 ID 검색"""
    params = urllib.parse.urlencode({
        'db': 'pubmed',
        'term': query,
        'retmax': max_results,
        'sort': 'date',
        'retmode': 'json',
    })
    url = f'{PUBMED_SEARCH_URL}?{params}'
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read())
    return data.get('esearchresult', {}).get('idlist', [])


def fetch_paper_details(pmids: list) -> list:
    """PubMed에서 논문 상세 정보 가져오기"""
    if not pmids:
        return []
    params = urllib.parse.urlencode({
        'db': 'pubmed',
        'id': ','.join(pmids),
        'retmode': 'xml',
    })
    url = f'{PUBMED_FETCH_URL}?{params}'
    with urllib.request.urlopen(url, timeout=30) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    papers = []
    for article in root.findall('.//PubmedArticle'):
        try:
            medline = article.find('.//MedlineCitation')
            pmid = medline.find('.//PMID').text
            art = medline.find('.//Article')
            title = art.find('.//ArticleTitle').text or ''
            abstract_parts = art.findall('.//Abstract/AbstractText')
            abstract = ' '.join(p.text or '' for p in abstract_parts)

            # 저자 정보
            authors = []
            for author in art.findall('.//AuthorList/Author'):
                last = author.find('LastName')
                first = author.find('ForeName')
                if last is not None and first is not None:
                    authors.append(f"{last.text} {first.text}")

            # 날짜
            pub_date = art.find('.//Journal/JournalIssue/PubDate')
            year = pub_date.find('Year').text if pub_date.find('Year') is not None else ''
            month = pub_date.find('Month').text if pub_date.find('Month') is not None else '01'

            # DOI
            doi = ''
            for eid in article.findall('.//PubmedData/ArticleIdList/ArticleId'):
                if eid.get('IdType') == 'doi':
                    doi = eid.text
                    break

            papers.append({
                'pmid': pmid,
                'title': title,
                'abstract': abstract,
                'authors': authors,
                'year': year,
                'month': month,
                'doi': doi,
            })
        except Exception as e:
            print(f"Error parsing article: {e}")
            continue
    return papers


def save_to_dynamodb(paper: dict, category: str):
    """DynamoDB에 논문 저장"""
    papers_table.put_item(Item={
        'paperId': f"pubmed-{paper['pmid']}",
        'source': 'pubmed',
        'category': category,
        'title': paper['title'],
        'abstract': paper['abstract'],
        'authors': paper['authors'],
        'doi': paper['doi'],
        'publishedDate': f"{paper['year']}-{paper['month']}",
        'pdfUrl': f"https://sci-hub.se/{paper['doi']}" if paper['doi'] else '',
        'createdAt': datetime.utcnow().isoformat(),
    })


def handler(event, context):
    """메인 핸들러 - 카테고리별 논문 수집 (rate limit 대응)"""
    import time
    total = 0
    for i, category in enumerate(CATEGORIES):
        try:
            if i > 0:
                time.sleep(1)  # PubMed rate limit: 3 req/sec without API key
            pmids = search_pubmed(category, max_results=10)
            time.sleep(0.5)
            papers = fetch_paper_details(pmids)
            for paper in papers:
                save_to_dynamodb(paper, category)
                total += 1
            print(f"[{category}] {len(papers)}편 수집 완료")
        except Exception as e:
            print(f"[{category}] 수집 실패: {e}")

    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': f'{total}편 논문 수집 완료',
            'timestamp': datetime.utcnow().isoformat(),
        }),
    }
