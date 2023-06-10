from flask import Flask, request
import hashlib

app = Flask(__name__)


def work(buffer='', iterations=1):
    output = hashlib.sha512(buffer).digest()
    for i in range(iterations - 1):
        output = hashlib.sha512(output).digest()
    return output


@app.route('/enqueue')
def enqueue():
    iterations = int(request.args.get('iterations', 1))
    body = request.data.decode('utf-8').encode()
    return str(work(iterations=iterations, buffer=body))


@app.route('/')
def main():
    return 'OK'


if __name__ == '__main__':
    app.run(port=5000)
