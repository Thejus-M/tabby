def main() -> None:
    import uvicorn

    uvicorn.run("tabby.main:app", host="0.0.0.0", port=8000)
