import base64
from PIL import Image
from io import BytesIO
import os

# higher quality JPEG encoding doesn't make much sense as we compress on iOS and the received image is smaller
# than what we get here
def encode_jpeg_image(image_path, max_long=None, max_short=None, quality=92):
    # Load the image
    with Image.open(image_path) as img:
        # Get the current size
        width, height = img.size

        # Determine the scaling factor to maintain aspect ratio
        aspect_ratio = width / height
        if width > height:  # Landscape orientation
            if max_long and width > max_long:
                width = max_long
                height = int(max_long / aspect_ratio)
            if max_short and height > max_short:
                height = max_short
                width = int(max_short * aspect_ratio)
        else:  # Portrait or square orientation
            if max_long and height > max_long:
                height = max_long
                width = int(max_long * aspect_ratio)
            if max_short and width > max_short:
                width = max_short
                height = int(max_short / aspect_ratio)

        # Resize the image with the new dimensions
        resized_img = img.resize((width, height), Image.Resampling.LANCZOS)

        # Save the resized image for debugging purposes
        base_name, ext = os.path.splitext(image_path)
        resized_image_path = f"{base_name}_resized.jpeg"
        resized_img.save(resized_image_path, format="JPEG", quality=quality)
        print(f"Resized image saved at: {resized_image_path}")

        # Save the resized image to a BytesIO buffer in JPEG format with medium quality
        buffer = BytesIO()
        resized_img.save(buffer, format="JPEG", quality=quality)

        # Get the base64 encoded string
        img_str = base64.b64encode(buffer.getvalue()).decode('utf-8')

        return img_str
