import os
import json
import boto3
import requests
from datetime import datetime

# Environment variables (set these in Lambda console)
news_api_key = os.environ.get('NEWS_API_KEY')
rds_host = os.environ.get('RDS_HOST')
rds_user = os.environ.get('RDS_USER')
rds_password = os.environ.get('RDS_PASSWORD')
rds_db = 'mynew_db'  # your database name here
s3_bucket = os.environ.get('S3_BUCKET')

def get_news():
    url = f'https://newsapi.org/v2/top-headlines?sources=techcrunch&apiKey={news_api_key}'
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to fetch news: {response.status_code} {response.text}")

def upload_to_s3(data):
    s3 = boto3.client('s3')
    s3_key = f'raw_data/news_raw{datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")}.json'
    s3.put_object(
        Bucket=s3_bucket,
        Key=s3_key,
        Body=json.dumps(data),
        ContentType='application/json'
    )
    print(f"Uploaded to S3: s3://{s3_bucket}/{s3_key}")

def create_database_if_not_exists(psycopg2):
    conn = psycopg2.connect(
        host=rds_host,
        port=5432,
        user=rds_user,
        password=rds_password,
        database='postgres'  
    )
    conn.autocommit = True
    cursor = conn.cursor()

    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (rds_db,))
    exists = cursor.fetchone()
    if not exists:
        print(f"Database {rds_db} does not exist. Creating...")
        cursor.execute(f'CREATE DATABASE {rds_db};')
        print(f"Database {rds_db} created.")
    else:
        print(f"Database {rds_db} already exists.")
    cursor.close()
    conn.close()

def create_table_if_not_exists(cursor):
    create_table_query = """
    CREATE TABLE IF NOT EXISTS my_articles (
        id SERIAL PRIMARY KEY,
        source_id VARCHAR(100),
        source_name VARCHAR(255),
        author TEXT,
        title TEXT,
        description TEXT,
        url TEXT,
        url_to_image TEXT,
        published_at TIMESTAMP,
        content TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        sentiment_score FLOAT
    );
    """
    cursor.execute(create_table_query)

def insert_into_rds(articles, cursor):
    insert_query = """
    INSERT INTO my_articles (
        source_id, source_name, author, title, description, url, url_to_image, published_at, content, sentiment_score
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
    """
    for article in articles:
        source = article.get('source', {})
        source_id = source.get('id')
        source_name = source.get('name')
        author = article.get('author')
        title = article.get('title')
        description = article.get('description')
        url = article.get('url')
        url_to_image = article.get('urlToImage')
        content = article.get('content')
        published_at = article.get('publishedAt')

        try:
            published_at_dt = datetime.fromisoformat(published_at.replace('Z', '+00:00')) if published_at else None
        except:
            published_at_dt = None

        cursor.execute(insert_query, (
            source_id, source_name, author, title, description, url, url_to_image,
            published_at_dt, content
        ))

def lambda_handler(event, context):
    try:
        import psycopg2
        print("psycopg2 imported successfully!")
    except ImportError as e:
        print(f"Import error: {e}")
        return {"statusCode": 500, "body": "psycopg2 import failed"}

    try:
        create_database_if_not_exists(psycopg2)
        news_data = get_news()
        upload_to_s3(news_data)
        articles = news_data.get("articles", [])

        if not articles:
            print("No articles found.")
            return {"statusCode": 204, "body": "No articles to insert."}

        conn = psycopg2.connect(
            host=rds_host,
            port=5432,
            user=rds_user,
            password=rds_password,
            database=rds_db
        )
        cursor = conn.cursor()
        create_table_if_not_exists(cursor)
        insert_into_rds(articles, cursor)
        conn.commit()
        cursor.close()
        conn.close()

        print("Inserted articles into RDS.")
        return {"statusCode": 200, "body": "News uploaded to S3 and RDS"}

    except Exception as e:
        print(f"Error: {e}")
        return {"statusCode": 500, "body": str(e)}
