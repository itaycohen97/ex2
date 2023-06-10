from flask import Flask, request, abort
import hashlib
import uuid
import json
import threading
import datetime
import time
import logging

from instance_handler import ec2_handler
from request_class import UserRequest, UserResponse


app = Flask(__name__)
with open("../data.json") as f:
    dictt = json.loads(f.read())
    aws_region = dictt["aws_region"]
    aws_secret_access_key = dictt["aws_secret_access_key"]
    aws_access_key_id = dictt["aws_access_key_id"]
    pem_name = dictt["new_pem_name"]
    aws_wrapper = ec2_handler(
        aws_region, aws_secret_access_key, aws_access_key_id, pem_name=pem_name)

result_queue = []
pending_queue = []
totall_requests = 0
req_per_interval = 0
max_workers = 5
interval = 10
stop_trd = False
data_lock, rm_lock, add_lock = None, None, None
current_workers = 0


def work(buffer="", iterations=1):
    output = hashlib.sha512(buffer).digest()
    for i in range(iterations - 1):
        output = hashlib.sha512(output).digest()
    return output


@app.route('/')
def hello():
    return ('OK')


@app.route('/enqueue')
def enqueue():
    # Document new request
    global req_per_interval, result_queue
    req_per_interval += 1

    iterations = int(request.args.get('iterations', 1))
    body = request.data.decode('utf-8').encode()

    work_id = str(uuid.uuid4())
    pending_queue.append(UserRequest(iterations, body.decode(), work_id))

    return work_id


@app.route("/get_work")
def get_work():
    global pending_queue
    if len(pending_queue) == 0:
        abort(404)
    latest = pending_queue.pop()
    return json.dumps(latest.to_dict())


@app.route("/add_to_done_queue")
def add_to_done_queue():
    global result_queue
    logging.info("got data from worker")
    data = request.args.get('data', "empty-data")
    uuid = request.args.get('uuid', "unknown")
    result_queue.append(UserResponse(data, uuid))
    return ""


@app.route('/pullCompleted')
def pullCompleted():
    top = int(request.args.get('top', 1))
    return json.dumps([item.to_dict() for item in result_queue[-top:]])


def count(event):
    try:
        while not event.is_set():
            global req_per_interval, totall_requests, interval, max_workers, pending_queue, aws_wrapper, current_workers
            current_instances = aws_wrapper.current_instances
            logging.info("num of instances = %d" % len(current_instances))
            if len(current_instances) == 0:
                logging.info("No workers, adding a new one")
                current_workers += 1
                aws_wrapper.add_ec2()
            elif len(pending_queue) > 0 and (datetime.datetime.now() - pending_queue[-1].start_time).seconds > 10:
                current_workers += 1
                logging.info("adding a worker -> this is worker %d out of %d" %
                             (current_workers, max_workers))
                aws_wrapper.add_ec2()
            elif len(current_instances) > 1 and len(pending_queue) == 0:
                aws_wrapper.kill_ec2_instance()
            logging.info(
                f"total requests for the last {interval} seconds -> {req_per_interval}")
            totall_requests += req_per_interval
            req_per_interval = 0
            time.sleep(interval)
        logging.info("stopping count!")
        return
    except KeyboardInterrupt:
        return


def runn():
    try:
        logging.info("runn log")
        print("runn print")
        global data_lock, rm_lock, add_lock
        data_lock = threading.Lock()
        rm_lock = threading.Lock()
        add_lock = threading.Lock()
        event = threading.Event()
        count_trd = threading.Thread(target=count, args=(event,))
        count_trd.start()
        app.run(host='0.0.0.0', port=5000, debug=False)
    finally:
        aws_wrapper.stop()
        event.set()
        count_trd.join()


if __name__ == "__main__":
    logging.info("main log")
    print("main print")
    runn()
