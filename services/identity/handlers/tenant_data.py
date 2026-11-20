"""Datos fijos de ServiDesk: tenants, equipos y cuentas demo.

Los UUID son deterministas (uuid5) para que el seed de los demás microservicios
pueda referenciar los mismos usuarios y equipos sin consultar ms-identity:

    user_id(tenant_code, email)  -> UUID del usuario
    team_id(tenant_code, nombre) -> UUID del equipo

Las cuentas demo coinciden con las del modo demo del frontend (frontend/src/mocks/db.ts).
"""

import uuid

NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "servidesk.cloud")

TENANTS = [
    {
        "code": "andina",
        "name": "Andina Retail",
        "domain": "andina.pe",
        "password": "Andina#2026",
        "demo": {
            "admin": ("carla.mendoza", "Carla Mendoza Ríos"),
            "agent": ("lucia.paredes", "Lucía Paredes Soto"),
            "customer": ("jorge.huaman", "Jorge Huamán Ríos"),
        },
    },
    {
        "code": "pacifico",
        "name": "Clínica Pacífico",
        "domain": "pacifico.pe",
        "password": "Pacifico#2026",
        "demo": {
            "admin": ("ricardo.vega", "Ricardo Vega Luna"),
            "agent": ("ana.quispe", "Ana Quispe Rojas"),
            "customer": ("marta.salazar", "Marta Salazar Cruz"),
        },
    },
    {
        "code": "unitec",
        "name": "UniTec Campus",
        "domain": "unitec.edu.pe",
        "password": "Unitec#2026",
        "demo": {
            "admin": ("diego.torres", "Diego Torres Paz"),
            "agent": ("sofia.ramos", "Sofía Ramos Díaz"),
            "customer": ("pablo.chavez", "Pablo Chávez León"),
        },
    },
]

TEAMS = [
    ("Mesa de Ayuda N1", "Primer contacto, triage y resolución rápida"),
    ("Soporte N2", "Diagnóstico avanzado de estaciones y aplicaciones"),
    ("Infraestructura", "Servidores, virtualización y almacenamiento"),
    ("Redes y Comunicaciones", "LAN, WAN, VPN y telefonía"),
    ("Aplicaciones de Negocio", "ERP, CRM y sistemas propios"),
    ("Seguridad de la Información", "Accesos, vulnerabilidades y cumplimiento"),
]


def schema_of(tenant_code):
    return f"tenant_{tenant_code}"


def user_id(tenant_code, email):
    return str(uuid.uuid5(NAMESPACE, f"{tenant_code}:user:{email.lower()}"))


def team_id(tenant_code, team_name):
    return str(uuid.uuid5(NAMESPACE, f"{tenant_code}:team:{team_name}"))


def demo_users(tenant):
    """Las 3 cuentas demo del tenant (admin, agent, customer)."""
    users = []
    for role in ("admin", "agent", "customer"):
        local, full_name = tenant["demo"][role]
        email = f"{local}@{tenant['domain']}"
        users.append({
            "id": user_id(tenant["code"], email),
            "email": email,
            "full_name": full_name,
            "role": role,
            "password": tenant["password"],
        })
    return users
