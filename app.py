from flask import Flask, render_template, jsonify
import requests
from bs4 import BeautifulSoup
from textblob import TextBlob
import sqlite3
import datetime
import logging
from urllib.parse import urljoin
import re

app = Flask(__name__)
app.secret_key = 'market_mood_secret_key'

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup
def init_db():
    conn = sqlite3.connect('market_mood.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS headlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT,
            source TEXT,
            sentiment_score REAL,
            sentiment_label TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

class HeadlineScraper:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0'
        }
        self.sources = {
            'Economic Times': {
                'url': 'https://economictimes.indiatimes.com/markets',
                'headline_selector': 'h3 a, h2 a, .eachStory h3 a'
            },
            'Business Standard': {
                'url': 'https://www.business-standard.com/markets',
                'headline_selector': 'h2 a, h3 a, .cardheading a'
            },
            'MoneyControl': {
                'url': 'https://www.moneycontrol.com/news/business/markets/',
                'headline_selector': 'h2 a, h3 a, .news_title a'
            }
        }

    def clean_headline(self, text):
        if not text:
            return ""
        text = re.sub(r'\s+', ' ', text.strip())
        text = re.sub(r'[^\w\s\-\.,!?%$]', '', text)
        return text[:200]

    def scrape_headlines(self):
        all_headlines = []

        for source_name, config in self.sources.items():
            try:
                logger.info(f"Scraping {source_name}...")
                response = requests.get(config['url'], headers=self.headers, timeout=10)
                response.raise_for_status()

                soup = BeautifulSoup(response.content, 'html.parser')
                links = soup.select(config['headline_selector'])

                headlines = []
                for link in links[:8]:
                    title = self.clean_headline(link.get_text())
                    if title and len(title) > 10:
                        url = link.get('href', '')
                        if url and not url.startswith('http'):
                            url = urljoin(config['url'], url)
                        headlines.append({
                            'title': title,
                            'url': url,
                            'source': source_name
                        })

                all_headlines.extend(headlines)
                logger.info(f"Found {len(headlines)} headlines from {source_name}")

            except Exception as e:
                logger.error(f"Error scraping {source_name}: {str(e)}")
                continue

        if not all_headlines:
            all_headlines = self.get_sample_headlines()

        return all_headlines[:15]

    def get_sample_headlines(self):
        return [
            {'title': 'Sensex rises 200 points on strong quarterly earnings', 'source': 'Sample', 'url': ''},
            {'title': 'Nifty touches new all-time high amid positive sentiment', 'source': 'Sample', 'url': ''},
            {'title': 'Banking stocks fall on RBI policy concerns', 'source': 'Sample', 'url': ''},
        ]

class SentimentAnalyzer:
    def __init__(self):
        self.bullish_keywords = ['rise', 'gain', 'surge', 'high', 'positive', 'growth', 'strong', 'boost', 'up', 'rally', 'bull', 'soar', 'climb', 'advance', 'profit']
        self.bearish_keywords = ['fall', 'drop', 'decline', 'low', 'negative', 'weak', 'crash', 'down', 'bear', 'plunge', 'slide', 'loss', 'concern', 'fear']

    def analyze_sentiment(self, text):
        if not text:
            return 0.0, 'Neutral'
        blob = TextBlob(text.lower())
        polarity = blob.sentiment.polarity

        text_lower = text.lower()
        bullish_count = sum(1 for word in self.bullish_keywords if word in text_lower)
        bearish_count = sum(1 for word in self.bearish_keywords if word in text_lower)

        if bullish_count > bearish_count:
            polarity = max(polarity, 0.2)
        elif bearish_count > bullish_count:
            polarity = min(polarity, -0.2)

        if polarity > 0.1:
            label = 'Bullish'
        elif polarity < -0.1:
            label = 'Bearish'
        else:
            label = 'Neutral'

        return round(polarity, 3), label

def save_headlines_to_db(headlines_data):
    conn = sqlite3.connect('market_mood.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM headlines WHERE timestamp < datetime("now", "-1 hour")')

    for headline in headlines_data:
        cursor.execute('''
            INSERT INTO headlines (title, url, source, sentiment_score, sentiment_label)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            headline['title'],
            headline['url'],
            headline['source'],
            headline['sentiment_score'],
            headline['sentiment_label']
        ))

    conn.commit()
    conn.close()

def get_cached_headlines():
    conn = sqlite3.connect('market_mood.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT title, url, source, sentiment_score, sentiment_label, timestamp
        FROM headlines 
        WHERE timestamp > datetime("now", "-30 minutes")
        ORDER BY timestamp DESC
    ''')

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return None

    headlines = []
    for row in rows:
        headlines.append({
            'title': row[0],
            'url': row[1],
            'source': row[2],
            'sentiment_score': row[3],
            'sentiment_label': row[4],
            'timestamp': row[5]
        })

    return headlines

def fetch_and_analyze_headlines():
    cached_headlines = get_cached_headlines()
    if cached_headlines:
        logger.info("Using cached headlines")
        return cached_headlines

    logger.info("Fetching fresh headlines...")
    scraper = HeadlineScraper()
    analyzer = SentimentAnalyzer()
    headlines = scraper.scrape_headlines()

    headlines_data = []
    for headline in headlines:
        score, label = analyzer.analyze_sentiment(headline['title'])
        headlines_data.append({
            'title': headline['title'],
            'url': headline['url'],
            'source': headline['source'],
            'sentiment_score': score,
            'sentiment_label': label
        })

    save_headlines_to_db(headlines_data)
    return headlines_data

def calculate_market_mood(headlines_data):
    if not headlines_data:
        return 0, {'bullish': 0, 'bearish': 0, 'neutral': 0}

    bullish_count = sum(1 for h in headlines_data if h['sentiment_label'] == 'Bullish')
    bearish_count = sum(1 for h in headlines_data if h['sentiment_label'] == 'Bearish')
    neutral_count = sum(1 for h in headlines_data if h['sentiment_label'] == 'Neutral')

    total = len(headlines_data)
    mood_score = ((bullish_count - bearish_count) / total * 100) if total > 0 else 0

    sentiment_counts = {
        'bullish': bullish_count,
        'bearish': bearish_count,
        'neutral': neutral_count
    }

    return round(mood_score, 1), sentiment_counts

# Flask Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/headlines')
def api_headlines():
    try:
        headlines_data = fetch_and_analyze_headlines()
        mood_score, sentiment_counts = calculate_market_mood(headlines_data)

        return jsonify({
            'success': True,
            'headlines': headlines_data,
            'mood_score': mood_score,
            'sentiment_counts': sentiment_counts,
            'last_updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_headlines': len(headlines_data)
        })
    except Exception as e:
        logger.error(f"Error in API: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
