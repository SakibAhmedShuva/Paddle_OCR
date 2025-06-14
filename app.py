# /paddle-ocr-webapp/app.py

import os
import uuid
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from paddleocr import PaddleOCR
import cv2 # Import OpenCV
import numpy as np # Import NumPy

# --- Configuration ---
# Define the folder to store uploaded images temporarily
UPLOAD_FOLDER = 'uploads'
# Define allowed file extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# --- App Initialization ---
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
CORS(app)  # Enable Cross-Origin Resource Sharing

# --- Global Model Initialization ---
# Initialize PaddleOCR. This is done once globally to avoid reloading the model on each request.
# The model files will be downloaded automatically on the first run.
print("Initializing PaddleOCR... This may take a moment on the first run.")
# Using use_angle_cls=False to match the notebook's behavior where the angle classifier was not used.
# Set show_log=False to keep the console clean.
ocr_model = PaddleOCR(lang='en', use_angle_cls=False, show_log=False)
print("PaddleOCR Initialized Successfully.")

# --- Helper Functions ---
def allowed_file(filename):
    """Checks if the uploaded file has an allowed extension."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_ocr_result(result):
    """
    Processes the raw result from PaddleOCR to format the text logically.
    This logic is an improved version of the one in the notebook, sorting text
    first by vertical position and then by horizontal position to reconstruct lines correctly.
    """
    if not result or not result[0]:
        return "No text found."

    text_coordinates = []
    # The result from paddleocr is wrapped in a list, so we access result[0]
    for item in result[0]:
        # item: [bounding_box, (text, confidence_score)]
        box = item[0]
        text = item[1][0]
        
        # Calculate the middle y-coordinate and starting x-coordinate of the text box
        y_coord = (box[0][1] + box[2][1]) / 2
        x_coord = box[0][0]
        
        text_coordinates.append({'text': text, 'y': y_coord, 'x': x_coord})

    # Sort items primarily by their vertical position (y), and secondarily by horizontal (x)
    text_coordinates.sort(key=lambda item: (item['y'], item['x']))
    
    # Group text items into lines based on vertical proximity
    line_threshold = 18  # Threshold to determine if text is on the same line
    formatted_lines = []
    if not text_coordinates:
        return ""

    current_line = [text_coordinates[0]]
    for i in range(1, len(text_coordinates)):
        prev_item = current_line[-1]
        current_item = text_coordinates[i]
        
        if abs(current_item['y'] - prev_item['y']) <= line_threshold:
            current_line.append(current_item)
        else:
            current_line.sort(key=lambda x: x['x'])
            formatted_lines.append(' '.join([item['text'] for item in current_line]))
            current_line = [current_item]
            
    if current_line:
        current_line.sort(key=lambda x: x['x'])
        formatted_lines.append(' '.join([item['text'] for item in current_line]))

    return '\n'.join(formatted_lines)


# --- Flask Routes ---
@app.route('/')
def index():
    """Serves the main HTML page for the frontend."""
    return render_template('index.html')

@app.route('/ocr-batch', methods=['POST'])
def upload_and_ocr_batch():
    """Handles multiple file uploads and performs OCR on each."""
    if 'files' not in request.files:
        return jsonify({'error': 'No files part in the request'}), 400
    
    files = request.files.getlist('files')
    
    if not files or all(file.filename == '' for file in files):
        return jsonify({'error': 'No files selected for uploading'}), 400
    
    results = []
    
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    
    for file in files:
        if file and allowed_file(file.filename):
            unique_filename = f"{uuid.uuid4()}_{file.filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            
            try:
                file.save(filepath)
                result = ocr_model.ocr(filepath, cls=False)
                formatted_text = process_ocr_result(result)
                
                results.append({
                    'filename': file.filename,
                    'text': formatted_text,
                    'status': 'success'
                })
                
            except Exception as e:
                results.append({'filename': file.filename,'text': '','status': 'error','error': str(e)})
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)
        else:
            results.append({'filename': file.filename if file else 'Unknown','text': '','status': 'error','error': 'File type not allowed'})
    
    return jsonify({'results': results})

# --- Route for "Augmented OCR" button ---
@app.route('/ocr-batch-augmented', methods=['POST'])
def upload_and_ocr_batch_augmented():
    """
    Handles "augmented" OCR by applying image preprocessing with OpenCV
    before running the OCR, providing a potentially different/better result.
    """
    if 'files' not in request.files:
        return jsonify({'error': 'No files part in the request'}), 400

    files = request.files.getlist('files')

    if not files or all(file.filename == '' for file in files):
        return jsonify({'error': 'No files selected for uploading'}), 400

    results = []

    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    for file in files:
        if file and allowed_file(file.filename):
            unique_filename = f"{uuid.uuid4()}_{file.filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)

            try:
                file.save(filepath)

                # --- START OF AUGMENTATION LOGIC ---
                
                # 1. Run OCR on the original image first
                original_result = ocr_model.ocr(filepath, cls=False)
                original_text = process_ocr_result(original_result)

                # 2. Preprocess the image using OpenCV for the "augmented" version
                img = cv2.imread(filepath)
                # Convert to grayscale
                gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                # Apply a binary threshold to get a black and white image
                _, augmented_img = cv2.threshold(gray_img, 128, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

                # 3. Run OCR on the processed NumPy array
                # PaddleOCR can take an image path or a NumPy array
                augmented_result = ocr_model.ocr(augmented_img, cls=False)
                augmented_text = process_ocr_result(augmented_result)
                
                # --- END OF AUGMENTATION LOGIC ---

                results.append({
                    'filename': file.filename,
                    'status': 'success',
                    'text': augmented_text,          # The "Enhanced Combined Text" is from our augmented image
                    'original_text': original_text,  # The "Original Image Text"
                    'variants': [                    # Populate variants for the UI
                        {'name': 'Original', 'word_count': len(original_text.split())},
                        {'name': 'Grayscale + Threshold', 'word_count': len(augmented_text.split())}
                    ]
                })

            except Exception as e:
                results.append({'filename': file.filename,'text': '','status': 'error','error': str(e)})
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)
        else:
            results.append({'filename': file.filename if file else 'Unknown','text': '','status': 'error','error': 'File type not allowed'})

    return jsonify({'results': results})


# Keep the original single file endpoint for backward compatibility
@app.route('/ocr', methods=['POST'])
def upload_and_ocr():
    """Handles the file upload and performs OCR."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected for uploading'}), 400
        
    if file and allowed_file(file.filename):
        if not os.path.exists(app.config['UPLOAD_FOLDER']):
            os.makedirs(app.config['UPLOAD_FOLDER'])
            
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filepath)
        
        try:
            result = ocr_model.ocr(filepath, cls=False)
            formatted_text = process_ocr_result(result)
            return jsonify({'text': formatted_text})
            
        except Exception as e:
            return jsonify({'error': f'An error occurred during OCR processing: {str(e)}'}), 500
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
    else:
        return jsonify({'error': 'File type not allowed'}), 400

# --- Main Execution ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)