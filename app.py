from flask import Flask, jsonify, Response, request, flash, redirect, url_for
from werkzeug.utils import secure_filename
from flask_cors import CORS

from autopipeline.data import QUIET_ML
import autopipeline
from autopipeline.Interactive import leap_demo
from autopipeline.util import formalize_desc, ensure_max_words

from datetime import datetime

import io
import sys
import time
import threading
import os
import pandas as pd
import subprocess

app = Flask(__name__)
CORS(app)

count_trigger = threading.Event()
user_msg = ""
desc = ""

query_history={}
user_input = None

dataname = ""

app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'uploads')

def remove_files_in_directory(directory):
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        if os.path.isfile(file_path) or os.path.islink(file_path):
            os.unlink(file_path)

def save_results(table, filename):
    # Assuming table is a DataFrame or compatible format
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    table.to_csv(path, index=False)
    return path

@app.route('/delete-files', methods=['POST'])
def delete_files():
    remove_files_in_directory('./static')
    remove_files_in_directory("./uploads")
    global query_history
    query_history = {}
    global user_input
    user_input = None
    return jsonify({"message": "File deleted"})

@app.route('/delete-dot-graph', methods=['POST'])
def delete_dot_graph():
    remove_files_in_directory('./static')
    return jsonify({"message": "File deleted"})

@app.route('/upload-csv', methods=['POST'])
def file_upload():
    file = request.files['file']
    if file:
        global dataname
        dataname = file.filename
        # filename = secure_filename(file.filename)
        filename = 'uploaded_file.csv'
        upload_folder = app.config['UPLOAD_FOLDER']
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        filepath = file.save(os.path.join(upload_folder, file.filename))
        # filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        df = pd.read_csv(filepath)
        headers = df.columns.tolist()
        print("*******", headers)
        return jsonify({'message': 'Headers retrieved', 'headers': headers})
    return jsonify({'message': 'No file received'}), 400

def query_wrapper():
    # print("########## Feedback: Hi! 🤓 To get started, please upload the data you want to analyze as a SINGLE file.")
    # dataset = QUIET_ML()  # Assuming this function is defined elsewhere and works correctly
    # try:
    #     qid = int(user_msg)
    #     if qid < 1 or qid > 40:
    #         print("########## Feedback: Please select an integer between 1 and 40.")
    #         return
    #     query_struct = dataset.query(qid) 
    #     result, augmented_table = leap(query_struct["query"], query_struct["data"], query_struct["desc"], saving_mode=False)
    # except:
    try:
        table = pd.read_csv(os.path.join(app.config['UPLOAD_FOLDER'], 'uploaded_file.csv'))
    except:
        print("########## Feedback: Please upload your data.")
        return
    print("CODE:import pandas as pd")
    print("CODE:table = pd.read_csv('"+dataname+"')")

    global desc
    # print("*******", desc)
    if len(desc) == 0:
        print("########## Feedback: Please provide description to your data.")
        return
    
    if user_msg in query_history:
        print("########## Warning: It seems like we already provided an answer for this query, do you want a new version?")
        global user_input
        while user_input == None:
            time.sleep(0.1)
        if not user_input:
            print("CACHE:", query_history[user_msg])
            return
        user_input = None


    print("########## Feedback: Got it! 🫡 Working on it now...")

    result, augmented_table = leap_demo(user_msg, table, desc, verbose = True, saving_mode=False)

    if result is not None:
        autopipeline.input = None
        now = datetime.now()
        timestamp = datetime.timestamp(now)
        print(f'VER NUMBER:{timestamp}')

        try:
            result = result.to_frame()
        except:
            pass
        try:
            result_demo = result.copy().head()
            for column in result_demo.columns:
                result_demo[column] = result_demo[column].apply(ensure_max_words)
            result_html = result_demo.to_html(classes='table table-stripped').replace('\n', '')
        except:
            result_html = result
        print(f'########## R-HTML:{result_html}')

        result_path = save_results(result, f'result{timestamp}.csv')
        query_history[user_msg] = result_path

    # remove_files_in_directory("./uploads")

def stream_output():
    while not count_trigger.is_set():
        time.sleep(0.1)
    # Create a new StringIO object to capture output
    remove_files_in_directory("./static")
    captured_output = io.StringIO()
    original_stdout = sys.stdout  # Backup the original stdout
    sys.stdout = captured_output  # Redirect stdout to the StringIO object

    # Start the count function in a separate thread
    count_thread = threading.Thread(target=query_wrapper)
    count_thread.start()

    # Stream the captured output to the client
    def generate():
        yield "data: start\n\n"
        while count_thread.is_alive():
            time.sleep(0.5)  # Give some time for output to accumulate
            captured_output.seek(0)
            output = captured_output.read()
            captured_output.seek(0)
            captured_output.truncate(0)
            if output:
                lines = output.splitlines()
                for line in lines:
                    yield f"data: {line}\n\n"
        # Check for any remaining output after thread ends
        captured_output.seek(0)
        output = captured_output.read()
        if output:
            lines = output.splitlines()
            for line in lines:
                yield f"data: {line}\n\n"
        sys.stdout = original_stdout  # Restore the original stdout
        captured_output.close()
        yield "data: complete\n\n"

    return Response(generate(), mimetype="text/event-stream")

@app.route('/start_count', methods=['POST'])
def start_count():
    data = request.get_json()
    global user_msg 
    user_msg = data.get('message')
    
    desc_dict = data.get('descriptions', {})
    global desc
    desc = formalize_desc(desc_dict)

    count_trigger.set()
    return jsonify({"message": "Counting started"})

@app.route('/warning', methods=['POST'])
def warning():
    data = request.get_json()
    global user_input
    user_input = data.get('warn', None)
    return jsonify({"message": "Counting started"})

@app.route('/leap-warning', methods=['POST'])
def leap_warning():
    data = request.get_json()
    autopipeline.input = data.get('warn', None)
    return jsonify({"message": "Counting started"})

@app.route('/process_key', methods=['POST'])
def process_key():
    data = request.get_json()
    autopipeline.api_key = data.get('apikey')
    autopipeline.organization = data.get('org')
    return jsonify({"message": "API key and ORG id recorded"})

@app.route('/test_stream', methods=['GET'])
def test_stream():
    return stream_output()

@app.route('/')
def hello_world():
    return 'Hello, World!'

if __name__ == '__main__':
    remove_files_in_directory("./static")
    app.run(debug=True, threaded=True)


