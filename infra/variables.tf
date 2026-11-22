variable "region" {
  description = "Región de AWS"
  type        = string
  default     = "us-east-1"
}

variable "correo" {
  description = "Tu correo, para etiquetas y alertas de presupuesto"
  type        = string
}

variable "mi_ip" {
  description = "Tu IP pública con /32, por ejemplo 181.50.10.20/32"
  type        = string
}

variable "tipo_instancia" {
  type    = string
  default = "c7g.xlarge"
}

variable "estado" {
  description = "running o stopped"
  type        = string
  default     = "running"
  validation {
    condition     = contains(["running", "stopped"], var.estado)
    error_message = "El estado debe ser running o stopped."
  }
}