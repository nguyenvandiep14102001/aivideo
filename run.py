import uvicorn

if __name__ == "__main__":
    # reload=False avoids multiple zombie servers fighting for port 7860 on Windows
    uvicorn.run("app.main:app", host="127.0.0.1", port=7860, reload=False)
