terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region

  # Etiquetas que se ponen solas en TODO lo que se cree (FinOps: saber qué cuesta qué)
  default_tags {
    tags = {
      Proyecto    = "agente-infra"
      Curso       = "CT07052"
      Responsable = var.correo
      GestionadoPor = "terraform"
    }
  }
}