import json
import random
import requests
import boto3
import urllib3
import time
import paramiko
import threading
from scp import SCPClient


class ec2_handler:
    def __init__(self, aws_region, aws_secret_access_key, aws_access_key_id, ssh_port=22, ip_cidr='0.0.0.0/0', ip_list=[]) -> None:
        urllib3.disable_warnings()
        self.lock = threading.Lock()
        self.ip_list = ip_list
        self.code_str = self.get_code_str()
        self.hostnames_str = self.get_hostnames_json()
        self.pem_file_name = "ex2_pem"
        self.pem_file_path = "../pem_key.pem"
        self.ec2 = boto3.client("ec2", aws_access_key_id=aws_access_key_id,
                                aws_secret_access_key=aws_secret_access_key, region_name=aws_region, verify=False)
        self._current_instances = []
        self.security_group_id = self.generate_security_group(
            ssh_port, ip_cidr)

    def get_workers(self):
        filters = [{
            'Name': 'tag:Name',
            'Values': ['Worker']
        },
            {'Name': 'instance-state-name', 'Values': ['running', 'pending']}]

        response = self.ec2.describe_instances(Filters=filters, )
        if not response.get("Reservations") or len(response.get("Reservations")) == 0:
            self._current_instances = []
        else:
            self._current_instances = []
            for reservation in response["Reservations"]:
                for instance in reservation["Instances"]:
                    if instance:
                        self._current_instances.append(
                            (instance["InstanceId"], instance["PublicDnsName"]))

        return self._current_instances

    def add_ec2(self):
        self.get_workers()
        print("Adding another Machine!")
        # Create the Ubuntu 20.04 instance
        ami_id = "ami-04f7efe62f419d9f5"
        instance_type = "t2.micro"
        response = self.ec2.run_instances(
            ImageId=ami_id,
            InstanceType=instance_type,
            KeyName=self.pem_file_name,
            SecurityGroupIds=[self.security_group_id],
            MinCount=1,
            MaxCount=1,
            TagSpecifications=[
                {
                    'ResourceType': 'instance',
                    'Tags': [
                        {
                            'Key': 'Name',
                            'Value': 'Worker'
                        },
                    ]
                },
            ],
        )
        # Get the instance ID
        instance_id = [instance['InstanceId']
                       for instance in response['Instances']][0]

        # Wait for the instance to start
        self.ec2.get_waiter('instance_running').wait(InstanceIds=[instance_id])

        # Get the public IP address
        hostname = self.ec2.describe_instances(
            InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]["PublicDnsName"]

        print("instance created!")
        self.get_workers()
        with self.lock:
            print("now setting data!")
            time.sleep(10)
            is_done = False
            while is_done != True:
                try:
                    self.set_ec2_data((instance_id, hostname))
                    is_done = True
                except Exception as e:
                    print(e)
        return self._current_instances

    def set_ec2_data(self, instance_tuple):
        instance_id = instance_tuple[0]
        hostname = instance_tuple[1]

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname, username='ec2-user',
                        key_filename=self.pem_file_path)
            print(f"SSH connection established to EC2 instance {instance_id}.")

        #   Copy file to the EC2 instance
            print("copying code files")
            with SCPClient(ssh.get_transport()) as scp:
                scp.put('../worker/worker.py', '/home/ec2-user/app.py')
                scp.put('../worker/worker_data.json',
                        '/home/ec2-user/worker_data.json')
            self.exec_cmd(ssh, command="chmod 777 /home/ec2-user/app.py")
            self.exec_cmd(ssh, command="chmod 777 /home/ec2-user/data.json")

            print("installing dependencies")
            self.exec_cmd(ssh, command="sudo yum update -y")
            self.exec_cmd(ssh, command="sudo yum -y install python3")
            self.exec_cmd(
                ssh, command="((nohup python3 /home/ec2-user/app.py >/home/ec2-user/app.log 2>&1)&)")
            print(self.exec_cmd(ssh, command="cat /home/ec2-user/data.txt"))

            # self.exec_cmd(
            # ssh, command="curl -O https://bootstrap.pypa.io/get-pip.py")
            # self.exec_cmd(ssh, command="python3 get-pip.py --user")
            # self.exec_cmd(ssh, command="pip install gunicorn")
            # self.exec_cmd(
            #     ssh, command="gunicorn -b 0.0.0.0:5000 app:app --daemon --error-logfile /opt/djangoprojects/reports/bin/gunicorn.errors --log-file /opt/djangoprojects/reports/bin/gunicorn.errors")
            print("Done!")

        except paramiko.AuthenticationException:
            print("Failed to authenticate SSH connection.")

        except paramiko.SSHException as e:
            print(f"SSH connection failed: {str(e)}")

        finally:
            ssh.close()
            print("SSH connection closed.")

    def generate_security_group(self, ssh_port, ip_cidr):
        group_name = "ex2_sec_group"
        response = self.ec2.describe_security_groups()
        security_groups = response['SecurityGroups']

        # Search for the security group by name
        for group in security_groups:
            if group['GroupName'] == group_name:
                for ip in self.ip_list:
                    try:
                        self.ec2.authorize_security_group_ingress(
                            GroupId=group['GroupId'],
                            IpPermissions=[
                                {
                                    "IpProtocol": "tcp",
                                    "FromPort": 5000,
                                    "ToPort": 5000,
                                    "IpRanges": [{"CidrIp": f"{ip}/32"}],
                                }
                            ],
                        )
                    except Exception as e:
                        print(e)
                return group['GroupId']

        response = self.ec2.create_security_group(
            GroupName=group_name,
            Description=group_name
        )

        # Get the security group ID
        group_id = response['GroupId']

        # Add SSH ingress rule to the security group
        self.ec2.authorize_security_group_ingress(
            GroupId=group_id,
            IpProtocol='tcp',
            FromPort=ssh_port,
            ToPort=ssh_port,
            CidrIp=ip_cidr
        )
        for ip in self.ip_list:
            self.ec2.authorize_security_group_ingress(
                GroupId=group_id,
                IpPermissions=[
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 5000,
                        "ToPort": 5000,
                        "IpRanges": [{"CidrIp": f"{ip}/32"}],
                    }
                ],
            )

        return group_id

    def kill_ec2_instance(self):
        if len(self._current_instances) == 1:
            return
        chosen_instance = random.choice(self.current_instances)
        instance_id = chosen_instance[0]

        # Terminate the EC2 instance
        response = self.ec2.terminate_instances(InstanceIds=[instance_id])

        # Check if termination was successful
        if response['TerminatingInstances'][0]['CurrentState']['Code'] == 32:
            print(f"EC2 instance with ID '{instance_id}' has been terminated.")
            with self.lock:
                self._current_instances.remove(chosen_instance)
        else:
            print(f"Failed to terminate EC2 instance with ID '{instance_id}'.")

    def stop(self):
        print("killing all instances!")
        response = self.ec2.terminate_instances(
            InstanceIds=[i[0] for i in self.current_instances])

        print(response)

    @property
    def current_instances(self):
        with self.lock:
            self.get_workers()
        return self._current_instances

    @staticmethod
    def get_code_str():
        with open("../worker/worker.py", "r") as f:
            data = f.read()
        return data

    @staticmethod
    def get_hostnames_json():
        with open("../worker/worker_data.json", "r") as f:
            data = f.read()
        return data

    @staticmethod
    def exec_cmd(ssh, command):
        # print("------------")
        # print(command)
        _, stdout, stderr = ssh.exec_command(command=command)
        output = stdout.read()
        err = stderr.read()
        # print(f"output = {output}")
        # print(f"err = {err}")
        return output.decode("utf-8")

    @staticmethod
    def get_my_ip():
        response = requests.get("http://icanhazip.com")
        return response.content.decode(encoding="utf-8").strip()


if __name__ == "__main__":
    # pass
    with open("../data.json") as f:
        dictt = json.loads(f.read())
        aws_region = dictt["aws_region"]
        aws_secret_access_key = dictt["aws_secret_access_key"]
        aws_access_key_id = dictt["aws_access_key_id"]
    ip_list = [ec2_handler.get_my_ip(), "11.12.13.14"]
    tmp = ec2_handler(aws_region, aws_secret_access_key,
                      aws_access_key_id, ip_list=ip_list)
    print(tmp.get_workers())
    # tmp.stop()
