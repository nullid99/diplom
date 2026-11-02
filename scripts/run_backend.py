import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env', interpolate=False)
    uvicorn.run(
        'backend.app.main:app',
        host=os.getenv('API_HOST', '127.0.0.1'),
        port=int(os.getenv('API_PORT', '8000')),
        reload=True,
        ws='wsproto',
        reload_dirs=[str(root / 'backend')],
    )
