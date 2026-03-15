# Auto GitIgnore
just stick this as an alias in your ~/.zshrc so that you can call `autogitignore c++` etc
```python
autogitignore # looks into dir to find corresponding file names and auto populate the ignore file
autogitignore c++ java # multiple langs concatenated into the ignore file
autogitignore --help # supported langs and usage

```

If languages are not supported, it will fetch templates from GitHub

Note: Web requests may need the web certificates to pull github .gitignore files:
``` shell
python3 -m pip install --upgrade certifi
```
