from flask import Flask
from supabase import create_client
from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "fallback-secret")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)
app.secret_key = SECRET_KEY

from app import routes  
