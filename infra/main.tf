data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical, la empresa que publica Ubuntu

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
  }
}

resource "aws_security_group" "ssh" {
  name        = "agente-infra-sg"
  description = "Solo SSH desde la IP del estudiante"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.mi_ip]
  }

  egress {
    description = "Salida a internet (Telegram, apt, Docker, API)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_key_pair" "llave" {
  key_name   = "agente-infra"
  public_key = file(pathexpand("~/.ssh/agente-infra.pub"))
}

resource "aws_instance" "agente" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.tipo_instancia
  key_name               = aws_key_pair.llave.key_name
  vpc_security_group_ids = [aws_security_group.ssh.id]
  user_data              = file("${path.module}/cloud-init.sh")

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  # Seguridad: exige IMDSv2 (protege las credenciales internas de la máquina)
  metadata_options {
    http_tokens = "required"
  }

  tags = {
    Name = "agente-infra"
  }
}

resource "aws_budgets_budget" "mensual" {
  name         = "agente-infra-mensual"
  budget_type  = "COST"
  limit_amount = "15"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.correo]
  }
}

resource "aws_ec2_instance_state" "agente" {
  instance_id = aws_instance.agente.id
  state       = var.estado
}