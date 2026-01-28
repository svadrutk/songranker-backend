import base64

# Read the font file
with open('app/static/fonts/Geist/variable/Geist[wght].ttf', 'rb') as f:
    font_data = f.read()

# Convert to base64
base64_font = base64.b64encode(font_data).decode('utf-8')

# Print the data URL
print(f"data:font/ttf;base64,{base64_font}")
