# 📄 PaperHub — AI 논문 검색 & 요약 & 영어학습 플랫폼

> 전 세계 2억+ 학술 논문을 실시간 검색하고, AI로 요약·분석·영어학습까지 하는 올인원 연구 플랫폼

## 📍 프로젝트 소개

연구자와 학생들은 매일 수많은 영어 논문을 읽어야 하지만, 논문 검색·요약·영어 학습을 각각 다른 도구에서 해야 하는 불편함이 있습니다.

PaperHub는 이 문제를 해결하기 위해 **논문 검색 + AI 요약 + 학술 영어 학습**을 하나의 플랫폼에 통합했습니다. PubMed, arXiv, OpenAlex 등 전 세계 주요 학술 DB에서 실시간으로 논문을 검색하고, Amazon Bedrock AI로 즉시 요약하며, 논문 기반 영어 학습 기능까지 제공합니다.

## 🔗 배포 주소

👉 **[PaperHub 바로가기](https://d1v25u4s2s5vh4.cloudfront.net)**

👉 **GitHub**: [https://github.com/heotaewoong/Paperhub](https://github.com/heotaewoong/Paperhub)

👉 **API**: `https://m3hkx12he5.execute-api.us-east-1.amazonaws.com/prod/`

<div align="center">
  <video src="intro_video_compressed.mp4" width="800" autoplay muted loop playsinline>
    브라우저가 비디오 태그를 지원하지 않습니다.
  </video>
</div> 

## 👥 We are

| 역할 | 담당 |
|------|------|
| 기획·개발·배포 | Kiro AI + 사용자 협업 |
| AI 엔진 | Amazon Bedrock (Nova Pro) |
| 인프라 | AWS CDK (TypeScript) |

---

## 💡 아키텍처

```
사용자 (Web/Mobile)
    │ HTTPS
    ▼
┌──────────────────────────────────────────────┐
│  AWS Cloud                                    │
│                                               │
│  CloudFront ──→ S3 (프론트엔드 SPA)            │
│       │                                       │
│       └──→ API Gateway (REST + CORS)          │
│                │                              │
│     ┌──────────┼──────────┐                   │
│     ▼          ▼          ▼                   │
│  Lambda:서빙  Lambda:요약  Lambda:추천          │
│  (실시간검색)  (Bedrock AI) (Bedrock AI)       │
│     │          │          │                   │
│     ▼          ▼          ▼                   │
│  DynamoDB    DynamoDB    S3                    │
│  (papers)   (bookmarks) (PDF캐시)             │
│                                               │
│  EventBridge ──(6시간)──→ Lambda:수집          │
│  Step Functions ──→ AI 병렬 처리               │
└──────────────────────────────────────────────┘
         │
    외부 API (실시간 검색)
    ├── PubMed (3,600만+)
    ├── arXiv (200만+)
    └── OpenAlex (2억+)
```

### 🔰 아키텍처 초보자 가이드

위 그림이 복잡해 보일 수 있지만, 실제로는 아주 단순한 흐름이에요. 하나씩 설명할게요.

#### 사용자가 검색 버튼을 누르면 무슨 일이 일어날까?

```
1️⃣ 사용자가 브라우저에서 "CRISPR" 검색
         │
2️⃣ CloudFront (전 세계 어디서든 빠르게 접속하게 해주는 CDN)
         │
3️⃣ API Gateway (요청을 받아서 적절한 Lambda에 전달하는 교통 경찰)
         │
4️⃣ Lambda:서빙 (실제 검색을 수행하는 서버리스 함수)
    ├── PubMed API 호출 → 의학 논문 결과
    ├── arXiv API 호출 → CS/물리 논문 결과
    └── OpenAlex API 호출 → 전 분야 논문 결과
         │
5️⃣ 결과를 합쳐서 사용자에게 반환 → 브라우저에 논문 카드 표시
```

#### AI 요약 버튼을 누르면?

```
1️⃣ 사용자가 "AI 요약" 클릭
         │
2️⃣ API Gateway → Lambda:요약
         │
3️⃣ Amazon Bedrock (AWS의 AI 서비스)에 논문 제목+초록 전달
    └── Nova Pro 모델이 한국어/영어로 요약 생성
         │
4️⃣ 요약 결과를 사용자에게 반환 → 카드에 요약 표시
```

#### 각 AWS 서비스가 하는 일 (쉽게 설명)

| 서비스 | 쉬운 비유 | 하는 일 |
|--------|----------|---------|
| **CloudFront** | 전 세계 배달 네트워크 | 한국에서 접속해도 빠르게 웹페이지를 보여줌 |
| **S3** | 파일 보관함 | 웹페이지(HTML), PDF 파일 등을 저장 |
| **API Gateway** | 안내 데스크 | "검색 요청이요" → 검색 담당에게, "요약 요청이요" → 요약 담당에게 전달 |
| **Lambda** | 알바생 (필요할 때만 일함) | 요청이 올 때만 실행되고, 안 쓰면 비용 0원. 서버 관리 불필요 |
| **DynamoDB** | 초고속 메모장 | 논문 정보, 북마크를 저장. 읽기/쓰기가 매우 빠름 |
| **Bedrock** | AI 두뇌 | 논문을 읽고 요약하고, 단어를 추출하고, 질문에 답변 |
| **EventBridge** | 알람 시계 | 6시간마다 "새 논문 수집해!" 하고 Lambda를 깨움 |
| **Step Functions** | 작업 관리자 | "요약이랑 추천을 동시에 해!" 같은 복잡한 작업 순서를 관리 |
| **CDK** | 설계도 | 위의 모든 서비스를 코드 한 줄로 자동 생성/배포 |

#### 왜 이런 구조를 썼을까?

- **서버리스**: 서버를 직접 관리할 필요 없음. AWS가 알아서 해줌
- **비용 효율**: 사용한 만큼만 과금. 아무도 안 쓰면 비용 거의 0원
- **자동 확장**: 사용자가 1명이든 1만 명이든 자동으로 처리
- **글로벌**: CloudFront 덕분에 전 세계 어디서든 빠르게 접속

---

## 🎯 프로젝트 컨셉

연구자가 논문을 **검색 → 요약 → 분석 → 영어학습 → 발표 준비**까지 하나의 플랫폼에서 할 수 있도록 합니다.

## 🔀 사용자 플로우

```
검색 → 논문 카드 → AI 요약(한/영/병합) → 상세보기 →
  ├── 📋 요약 (한줄 + 전반적 + 키워드 + 난이도)
  ├── 📈 분석 (인용 논문 + 연구 트렌드 차트)
  ├── 📖 영어학습 (단어장/문장해부/영작/퀴즈/TTS/발표)
  ├── 🤖 AI 튜터 (논문 Q&A 채팅)
  ├── ❓ 연구질문 (비판적 사고 질문 생성)
  └── 📊 슬라이드 (발표자료 자동 생성)
```

---

## 💻 서비스 소개

### 🔍 실시간 멀티소스 검색

- **PubMed**: 생명과학/의학 3,600만+ 논문
- **arXiv**: CS/물리/수학 프리프린트 200만+
- **OpenAlex**: 전 분야 2억+ (인용 수 포함)
- 트렌딩 키워드 원클릭 검색
- 관련도순 / 인용수순 / 최신순 정렬
- `Cmd+K` 키보드 단축키

### 🤖 AI 논문 요약

- **언어 선택**: 🇰🇷 한국어 / 🇺🇸 English / 🌐 둘 다
- **한줄 요약**: 핵심을 한 문장으로
- **전반적 요약**: 연구 배경 → 방법론 → 결과 → 결론 구조화
- **키워드 자동 추출** + **난이도 평가** (입문/중급/고급)

### 📈 논문 분석

- **인용 논문**: 이 논문을 인용한 논문 목록 (OpenAlex)
- **연구 트렌드**: 연도별 논문 수 바 차트 (2005~현재)
- **논문 비교**: 두 논문 선택 → AI가 방법론/결과/강점/한계 비교

### 📖 학술 영어 학습 (8가지 기능)

| 기능 | 설명 |
|------|------|
| 🔤 단어장 | 논문에서 학술 단어 10개 추출 + 뜻/발음/예문 |
| 📝 문장 해부 | 복잡한 문장 구조 분석 (주어/동사/목적어 + 직역/의역) |
| ✍️ 영작 연습 | 한국어 요약 보고 영어로 작성 → AI 피드백 + 모범 답안 + 문법 교정 |
| 📝 퀴즈 | 빈칸 채우기/문맥 추론/내용 이해 5문제 + 점수 |
| 📚 학술 표현 | 서론/방법론/결과/결론별 학술 영어 패턴 |
| 🔊 TTS | 브라우저 음성으로 초록 읽어주기 (속도 조절) |
| 🎤 발표 준비 | 2분 영어 발표 스크립트 + 예상 질문 + 학회 표현 |
| 📈 학습 통계 | 마스터/학습중/새단어 + 진행률 바 |

### 🧠 에빙하우스 복습 시스템

- **간격 반복**: 1일 → 4일 → 7일 → 14일 → 28일
- localStorage 기반 학습 기록
- 오늘 복습할 단어 자동 표시
- 플래시카드 방식 복습

### 📥 내보내기

- **마크다운** (.md) 다운로드
- **CSV** (.csv) 다운로드 — Google Sheets/Excel 호환
- TTS 반복 텍스트 포함

### 🤖 AI 튜터 (Chat with Paper)

- 논문에 대해 자유롭게 질문
- 대화 이력 유지
- "이 방법론이 왜 좋은 거야?" 같은 질문 가능

### ❓ AI 연구 질문 생성

- 비판/확장/방법론/응용/한계 5가지 유형
- 각 질문에 생각해볼 포인트 제공

### 📊 발표 슬라이드 자동 생성

- 5장짜리 슬라이드 (제목/배경/방법론/결과/결론)
- HTML / 텍스트 다운로드
- 발표자 노트 포함

### 🔥 읽기 스트릭

- 매일 읽기 챌린지
- 연속 일수 + 총 읽은 논문 수
- AI 요약 생성 시 자동 기록

### 📄 내 논문 분석

- DOI 입력으로 논문 가져오기
- 가져온 논문에 모든 AI 기능 적용 가능

---

## 🛠 기술 스택

| 분류 | 도구 |
|------|------|
| 프론트엔드 | HTML/CSS/JavaScript (SPA) |
| 백엔드 | AWS Lambda (Python 3.12) × 4 |
| AI | Amazon Bedrock (Nova Pro) |
| DB | DynamoDB × 2 |
| 스토리지 | S3 (PDF 캐시 + 프론트엔드) |
| CDN | CloudFront |
| API | API Gateway (REST + CORS) |
| 스케줄러 | EventBridge (6시간 주기) |
| 워크플로우 | Step Functions |
| IaC | AWS CDK (TypeScript) |
| 검색 API | PubMed, arXiv, OpenAlex |
| TTS | Web Speech API |
| PDF 파싱 | PDF.js |

---

## 📂 프로젝트 구조

```
📁 paperhub/
├── 📁 bin/
│   └── ⚡ paperhub.ts           # CDK 앱 엔트리포인트
├── 📁 lib/
│   └── ⚡ paperhub-stack.ts     # CDK 인프라 정의 (전체 스택)
├── 📁 lambda/
│   ├── 📁 ingest/
│   │   └── 🐍 index.py          # 논문 수집 (PubMed, 30개 카테고리)
│   ├── 📁 serve/
│   │   └── 🐍 index.py          # API 서빙 + 실시간 검색 + 트렌드 + 인용
│   ├── 📁 ai-summarize/
│   │   └── 🐍 index.py          # AI 요약 + 영어학습 + 튜터 + 슬라이드
│   └── 📁 ai-recommend/
│       └── 🐍 index.py          # AI 추천
├── 📁 frontend/
│   └── 🌐 index.html            # SPA 프론트엔드 (전체 UI)
├── 📄 cdk.json
├── 📄 package.json
├── 📄 tsconfig.json
└── 📄 README.md
```

---

## 🔗 API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/papers` | 저장된 논문 목록 |
| GET | `/papers/{id}` | 논문 상세 |
| POST | `/papers/{id}/summarize` | AI 요약/영어학습/튜터/슬라이드 |
| GET | `/search?q=키워드` | 실시간 멀티소스 검색 |
| GET | `/trends?q=키워드` | 연구 트렌드 (연도별) |
| GET | `/citations?doi=...` | 인용 논문 목록 |
| GET/POST/DELETE | `/bookmarks` | 북마크 CRUD |

---

## 🚀 배포 방법

```bash
# 1. 의존성 설치
cd paperhub && npm install

# 2. AWS 자격 증명 설정
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_SESSION_TOKEN="..."
export AWS_DEFAULT_REGION="us-east-1"

# 3. CDK 부트스트랩 (최초 1회)
npx cdk bootstrap

# 4. 배포
npx cdk deploy

# 5. 프론트엔드 업로드
aws s3 cp frontend/index.html s3://paperhub-frontend-{ACCOUNT}/index.html \
  --content-type "text/html; charset=utf-8" --cache-control "no-cache"

# 6. 논문 수집
aws lambda invoke --function-name paperhub-ingest /tmp/result.json
```

---

## 🧹 리소스 정리

```bash
npx cdk destroy
```

---

## 📌 향후 개선 계획

- 모바일 반응형 UI 개선
- 논문 PDF 전문 분석 (RAG)
- 오디오 요약 (Amazon Polly)
- 다국어 번역 지원
- 사용자 인증 (Cognito)
- 논문 컬렉션/폴더 기능
