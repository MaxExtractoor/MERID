import base64
import pathlib

# Create a valid 16x16 transparent ICO file
# ICO format: 6-byte header + 16-byte image directory + 40-byte BMP header + pixel data
ico_data = (
    b'\x00\x00\x01\x00\x01\x00'  # ICO header (2 reserved, 1 type, 1 image)
    b'\x10\x10\x00\x00\x01\x00\x20\x00\x00\x00\x00\x00\x00\x00\x00\x00'  # Image directory (16x16, 32bpp, 1KB offset)
    b'\x28\x00\x00\x00\x10\x00\x00\x00\x20\x00\x00\x00\x01\x00\x20\x00'  # BMP header (40 bytes, 16x16, 32bpp)
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'  # BMP header continuation
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rest of BMP header
    b'\x00\x00\x00\x00' * 256  # 16x16 transparent pixels (4 bytes per pixel)
)

# Write the ICO file
favicon_path = pathlib.Path('c:/Dev/MERID/favicon.ico')
favicon_path.write_bytes(ico_data)
print(f"Created valid favicon.ico: {favicon_path.stat().st_size} bytes")
