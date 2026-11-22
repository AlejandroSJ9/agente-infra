output "ami_ubuntu" {
  value = data.aws_ami.ubuntu.id
}

output "ip_publica" {
  value = aws_instance.agente.public_ip
}

output "conectarse" {
  value = "ssh -i ~/.ssh/agente-infra ubuntu@${aws_instance.agente.public_ip}"
}