import hashlib
import json
import time
import random
import requests


class Worker:
    def __init__(self, data_file_path) -> None:
        with open(data_file_path, "r") as f:
            self.endpoints_data = json.loads(f.read())
        self.hostnames = [i["hostname"] for i in self.endpoints_data]

    def work(self, buffer='', iterations=1):

        buffer = buffer.encode("utf-8")
        output = hashlib.sha512(buffer).digest()
        for i in range(iterations - 1):
            output = hashlib.sha512(output).digest()
        return output

    def proccess_work(self, data):
        output = self.work(data["body"], iterations=int(data["iterations"]))
        self.send_data_to_all({"uuid": data["uuid"], "data": output})

    def send_data_to_all(self, data):
        for hostname in self.hostnames:
            requests.get("http://%s:5000/add_to_done_queue" %
                         hostname, params=data)
            # requests.get("http://%s/add_to_done_queue" %
            #  hostname, params=data)

    def loop(self):
        while True:
            try:
                work = self.get_work()
                if work:
                    work = json.loads(work)
                    print(work)
                    self.proccess_work(work)
                time.sleep(2)
            except Exception as e:
                print(f"Exception -> {e}, {e.__dict__}")

    def get_work(self):
        hostname = random.choice(self.hostnames)
        response = requests.get("http://%s:5000/get_work" % hostname)
        # response = requests.get("http://%s/get_work" % hostname)
        if response.status_code == 200:
            return response.text
        return None


if __name__ == "__main__":
    print("starting")
    worker = Worker("/home/ec2-user/worker_data.json")
    # worker = Worker(
    # "/Users/itayc/Documents/IDC/שנה ג׳/Cloud Computing/ex2/worker/worker_data.json")
    worker.loop()
    # data = {'iterations': 3, 'body': 'sasd',
    #         'uuid': '6d8f10ed-aed9-490f-a663-6c2894731b9b'}
    # output = worker.work(data["body"], iterations=int(data["iterations"]))
    # print(output)
