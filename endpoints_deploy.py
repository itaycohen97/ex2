import json
import os
import random
import requests
import boto3
import urllib3
import time
import paramiko
import threading
from scp import SCPClient


class endpoints_deploy:
    def __init__(self, aws_region, aws_secret_access_key, aws_access_key_id, ssh_port=22, ip_cidr='0.0.0.0/0', ip_list=[], pem_name="ex2_pem") -> None:
        urllib3.disable_warnings()
        self.pem_file_path = "./pem_key.pem"
        self.pem_name = pem_name
        self.ip_list = ip_list
        self.endpoints_hostnames = []
        self.ec2 = boto3.client("ec2", aws_access_key_id=aws_access_key_id,
                                aws_secret_access_key=aws_secret_access_key, region_name=aws_region, verify=False)
        self.security_group_id = self.generate_security_group(
            ssh_port, ip_cidr)

    def init_deploymeny(self, num_of_instances=1):
        # Generate a key pair
        key_pair_name = self.pem_name
        key_pair = self.ec2.create_key_pair(KeyName=key_pair_name)

        # Save the key pair to a file
        key_pair_file = key_pair['KeyMaterial']
        with open(self.pem_file_path, 'w') as f:
            f.write(key_pair_file)
        os.chmod(self.pem_file_path, 400)

        print(f"Deploying {num_of_instances} machine(s)!")
        # Create the Ubuntu 20.04 instance
        ami_id = "ami-04f7efe62f419d9f5"
        instance_type = "t2.micro"
        response = self.ec2.run_instances(
            ImageId=ami_id,
            InstanceType=instance_type,
            KeyName=key_pair_name,
            SecurityGroupIds=[self.security_group_id],
            MinCount=num_of_instances,
            MaxCount=num_of_instances,
            TagSpecifications=[
                {
                    'ResourceType': 'instance',
                    'Tags': [
                        {
                            'Key': 'Name',
                            'Value': 'Endpoint'
                        },
                    ]
                },
            ],


        )
        # Get the instance ID
        instances_id = [instance['InstanceId']
                        for instance in response['Instances']]

        # Wait for the instance to start
        self.ec2.get_waiter('instance_running').wait(InstanceIds=instances_id)

        instances_data = self.ec2.describe_instances(InstanceIds=instances_id)
        # print(instances_data)

        instances = [{"public_ip": data["PublicIpAddress"],
                      "hostname": data["PublicDnsName"]} for data in instances_data["Reservations"][0]["Instances"]]
        self.endpoints_hostnames = [data["PublicDnsName"]
                                    for data in instances_data["Reservations"][0]["Instances"]]

        with open("./worker/worker_data.json", "w") as f:
            f.write(json.dumps(instances))

        print("instances created!")
        time.sleep(10)
        print("now setting data!")
        self.set_ec2_data(instances)

    def set_ec2_data(self, instances):
        for instance in instances:
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(instance["hostname"], username='ec2-user',
                            key_filename=self.pem_file_path)
                print("SSH connection established to EC2 instance.")

            #   Copy file to the EC2 instance
                print("copying code files")
                self.exec_cmd(ssh, command="mkdir /home/ec2-user/ex2")
                self.exec_cmd(ssh, command="cd /home/ec2-user/ex2")
                self.exec_cmd(ssh, command="mkdir /home/ec2-user/ex2/server")
                self.exec_cmd(ssh, command="mkdir /home/ec2-user/ex2/worker")

                with SCPClient(ssh.get_transport()) as scp:
                    scp.put('./server/instance_handler.py',
                            '/home/ec2-user/ex2/server/instance_handler.py')
                    scp.put('./server/request_class.py',
                            '/home/ec2-user/ex2/server/request_class.py')
                    scp.put('./server/server.py',
                            '/home/ec2-user/ex2/server/server.py')
                    scp.put('./worker/worker.py',
                            '/home/ec2-user/ex2/worker/worker.py')
                    scp.put('./worker/worker_data.json',
                            '/home/ec2-user/ex2/worker/worker_data.json')
                    scp.put('./pem_key.pem',
                            '/home/ec2-user/ex2/pem_key.pem')
                    scp.put('./data.json',
                            '/home/ec2-user/ex2/data.json')

                print("installing dependencies")
                self.exec_cmd(ssh, command="sudo yum update -y")
                self.exec_cmd(ssh, command="sudo yum -y install python3")
                self.exec_cmd(
                    ssh, command="curl -O https://bootstrap.pypa.io/get-pip.py")
                self.exec_cmd(ssh, command="python3 get-pip.py --user")
                self.exec_cmd(ssh, command="pip install boto3")
                self.exec_cmd(ssh, command="pip install paramiko")
                self.exec_cmd(ssh, command="pip install scp")
                self.exec_cmd(ssh, command="pip install flask")
                self.exec_cmd(ssh, command="pip install gunicorn")
                self.exec_cmd(ssh, command="echo ''> /home/ec2-user/app.log")
                self.exec_cmd(ssh, command="chmod 777 /home/ec2-user/app.log")
                self.exec_cmd(
                    ssh, command="(cd ex2/server;(nohup python3 server.py >/home/ec2-user/app.log 2>&1)&)")
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
                                    "IpRanges": [{"CidrIp": ip_cidr}],
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
        self.ec2.authorize_security_group_ingress(
            GroupId=group_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 5000,
                    "ToPort": 5000,
                    "IpRanges": [{"CidrIp": ip_cidr}],
                }
            ],
        )

        return group_id

    def stop(self):
        print("killing all instances!")
        response = self.ec2.terminate_instances(
            InstanceIds=[i[0] for i in self._current_instances])

        print(response)

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
    with open("data.json") as f:
        dictt = json.loads(f.read())
        aws_region = dictt["aws_region"]
        new_pem_name = dictt["new_pem_name"]
        aws_secret_access_key = dictt["aws_secret_access_key"]
        aws_access_key_id = dictt["aws_access_key_id"]
    ip_list = [endpoints_deploy.get_my_ip()]
    tmp = endpoints_deploy(aws_region,
                           aws_secret_access_key, aws_access_key_id, ip_list=ip_list, pem_name=new_pem_name)
    tmp.init_deploymeny(2)
    print("Deployment is DONE! so what now?")
    print("This is how you communicate with the server:")
    for i in tmp.endpoints_hostnames:
        print(f"- http://{i}:5000/")
    # tmp.stop()
