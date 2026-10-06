"""Controlador do Go2 solto no chao: marcha crawl com PD nos torques.

Copiado de cinematica/cenario_livre.py (sem a cena e as cameras, que o
estudio tem proprias) para que esta pasta rode sozinha. O passo 3 vai
construir a biblioteca de acoes em cima do MotorDinamico.
"""
import math

from mujoco_carga import mujoco
import numpy as np

PERNAS = ["FL", "FR", "RL", "RR"]

L_ABD = 0.0955
L_COXA = 0.213
L_CANELA = 0.213
R_PE = 0.022

QUADRIL_XY = {"FL": (0.1934, 0.0465), "FR": (0.1934, -0.0465),
              "RL": (-0.1934, 0.0465), "RR": (-0.1934, -0.0465)}
LADO = {"FL": 1.0, "FR": -1.0, "RL": 1.0, "RR": -1.0}
POSE_HOME = np.array([0.0, 0.9, -1.8] * 4)

PARAM_MARCHA = dict(
    T=0.60, duty=0.85, balanco=0.09, altura=0.26, abertura=0.06,
    fases={"FL": 0.00, "RR": 0.25, "FR": 0.50, "RL": 0.75},
)

PARAM_CTRL = dict(
    kp=90.0, kd=2.0, kr=0.30, ki=0.25, ilim=(0.10, 0.08, 0.15),
    kpz=0.25, kdz=0.05, krp=0.60, kdrp=0.05, krr=0.60, kdrr=0.05,
    aclip=0.045, wfade=0.30, wfilt=0.35, vfilt=0.05, slew=2.0,
)

VEL_MAX = 0.60
GIRO_MAX = 0.80


def ik_perna(px, py, pz, lado):
    """Devolve (q, alcancavel). Sem grampear alvo fora de alcance: quem chama
    decide o que fazer. O original desta bancada grampeava e devolvia resposta
    errada calada -- ver a secao de cinematica inversa no LEIAME."""
    rYZ2 = py * py + pz * pz
    abd2 = L_ABD * L_ABD
    if rYZ2 < abd2:
        return (0.0, 0.0, 0.0), False
    c = math.sqrt(rYZ2 - abd2)
    r = math.hypot(px, c)
    soma = L_COXA + L_CANELA
    dif = abs(L_COXA - L_CANELA)
    if r > soma or r < dif:
        return (0.0, 0.0, 0.0), False
    q1 = math.atan2(pz, py) + math.atan2(c, lado * L_ABD)
    cos3 = (r * r - L_COXA ** 2 - L_CANELA ** 2) / (2 * L_COXA * L_CANELA)
    q3 = -math.acos(max(-1.0, min(1.0, cos3)))
    phi = math.atan2(-L_CANELA * math.sin(q3), L_COXA + L_CANELA * math.cos(q3))
    return (q1, math.atan2(-px, c) + phi, q3), True


def quat_de_yaw(psi):
    return np.array([math.cos(psi / 2), 0.0, 0.0, math.sin(psi / 2)])


def yaw_de_quat(q):
    w, x, y, z = q
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def mat_de_quat(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def fase_da_perna(fase, perna, prm):
    return (fase + prm["fases"][perna]) % 1.0


class MotorDinamico:
    """Marcha crawl com controle PD nos torques e dinamica completa integrada.
    O robo pode cair; quando cai, se levanta no lugar."""

    def __init__(self, m, d):
        self.m, self.d = m, d
        self.prm = dict(PARAM_MARCHA)
        self.p = dict(PARAM_CTRL)
        self.fase = 0.0
        self.cmd_f = np.zeros(3)
        self.vm = np.zeros(3)
        self.iv = np.zeros(3)
        self.wf = np.zeros(3)
        self.limites = m.actuator_ctrlrange.copy()
        self.tau = np.zeros(m.nu)
        self.quedas = 0
        self.recusados = 0
        self._ini = (0.0, 0.0, 0.0)

    def reiniciar(self, x=0.0, y=0.0, psi=0.0):
        m, d = self.m, self.d
        # Sem keyframe: a cena do estudio tira o "home" do go2.xml, porque o
        # tamanho dele deixa de bater quando entram objetos soltos.
        mujoco.mj_resetData(m, d)
        d.qpos[0], d.qpos[1] = x, y
        d.qpos[2] = self.prm["altura"] + R_PE + 0.02
        d.qpos[3:7] = quat_de_yaw(psi)
        d.qpos[7:19] = POSE_HOME
        d.qvel[:] = 0.0
        d.ctrl[:] = 0.0
        self.fase = 0.0
        for v in (self.cmd_f, self.vm, self.iv, self.wf):
            v[:] = 0.0
        self._ini = (x, y, psi)
        mujoco.mj_forward(m, d)

    def zerar_marcha(self):
        """Comeca a marcha do zero depois de uma pose (sentar, deitar...)."""
        self.fase = 0.0
        for v in (self.cmd_f, self.vm, self.iv, self.wf):
            v[:] = 0.0

    def manter_pose(self, q_des, dt):
        """PD direto nas juntas, sem marcha: para sentar, deitar e levantar.
        Devolve True se o corpo tombou (de lado ou de cabeca para baixo)."""
        m, d = self.m, self.d
        p = self.p
        self.tau[:] = p["kp"] * (q_des - d.qpos[7:19]) - p["kd"] * d.qvel[6:18]
        d.ctrl[:] = np.clip(self.tau, self.limites[:, 0], self.limites[:, 1])
        for _ in range(max(1, int(round(dt / m.opt.timestep)))):
            mujoco.mj_step(m, d)
        if not np.all(np.isfinite(d.qpos)):
            return True
        R = mat_de_quat(d.qpos[3:7])
        return bool(R[2, 2] < 0.55)

    def caiu(self):
        d = self.d
        if not np.all(np.isfinite(d.qpos)):
            return True
        R = mat_de_quat(d.qpos[3:7])
        return bool(R[2, 2] < 0.55 or d.qpos[2] < 0.12)

    def passo(self, cmd, dt):
        p, prm, m, d = self.p, self.prm, self.m, self.d
        self.cmd_f += np.clip(np.array(cmd, float) - self.cmd_f,
                              -p["slew"] * dt, p["slew"] * dt)
        vx_c, vy_c, wz_c = self.cmd_f
        andando = abs(vx_c) > 0.02 or abs(vy_c) > 0.02 or abs(wz_c) > 0.05
        if not andando and self.fase != 0.0:
            # Parar no meio de um passo faz o pe no ar cair de uma vez: o robo
            # da um pulo e escorrega. Termina o ciclo ate todas as patas
            # pousarem, so' entao congela.
            if all(fase_da_perna(self.fase, pn, prm) < prm["duty"] for pn in PERNAS):
                self.fase = 0.0
            else:
                andando = True
        if andando:
            self.fase = (self.fase + dt / prm["T"]) % 1.0

        quat = d.qpos[3:7]
        R = mat_de_quat(quat)
        psi = yaw_de_quat(quat)
        c, s = math.cos(psi), math.sin(psi)
        Rz = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
        Rt = Rz.T @ R
        v_rumo = Rz.T @ d.qvel[0:3]
        # qvel[3:6] da junta livre vem no referencial do CORPO (qvel[0:3] no
        # do mundo). Levar ao referencial do rumo e' Rt, nao Rz.T: com Rz.T o
        # robo so' ficava de pe andando para +x e caia nos outros rumos.
        w_rumo = Rt @ d.qvel[3:6]
        rol = math.atan2(Rt[2, 1], Rt[2, 2])
        arf = math.atan2(-Rt[2, 0], math.hypot(Rt[2, 1], Rt[2, 2]))

        b = p["vfilt"]
        self.vm[0] += b * (v_rumo[0] - self.vm[0])
        self.vm[1] += b * (v_rumo[1] - self.vm[1])
        self.vm[2] += b * (w_rumo[2] - self.vm[2])
        self.wf += p["wfilt"] * (w_rumo - self.wf)

        if andando:
            self.iv += p["ki"] * (np.array([vx_c, vy_c, wz_c]) - self.vm) * dt
            self.iv = np.clip(self.iv, -np.array(p["ilim"]), np.array(p["ilim"]))
        else:
            # zerar na hora: decaindo devagar, o integrador empurrava o robo
            # uns 15 cm para tras depois de parar
            self.iv[:] = 0.0

        dz = float(np.clip(p["kpz"] * (prm["altura"] + R_PE - d.qpos[2])
                           - p["kdz"] * d.qvel[2], -0.05, 0.05))
        esc = max(0.0, 1.0 - abs(wz_c) / p["wfade"])
        cl = p["aclip"]
        c_rol = esc * float(np.clip(p["krr"] * rol + p["kdrr"] * self.wf[0], -cl, cl))
        c_arf = esc * float(np.clip(p["krp"] * arf + p["kdrp"] * self.wf[1], -cl, cl))

        T_apoio = prm["T"] * prm["duty"]
        q_des = np.zeros(12)
        for i, perna in enumerate(PERNAS):
            hx, hy = QUADRIL_XY[perna]
            lado = LADO[perna]
            ny = hy + lado * (L_ABD + prm["abertura"])
            ph = fase_da_perna(self.fase, perna, prm)
            apoio = (not andando) or ph < prm["duty"]
            npx = self.vm[0] - wz_c * ny
            npy = self.vm[1] + wz_c * hx
            hsx = float(np.clip(0.5 * npx * T_apoio, -0.16, 0.16))
            hsy = float(np.clip(0.5 * npy * T_apoio, -0.11, 0.11))
            rx = float(np.clip(p["kr"] * (self.vm[0] - vx_c) - self.iv[0], -0.13, 0.13))
            ry = float(np.clip(p["kr"] * (self.vm[1] - vy_c) - self.iv[1], -0.09, 0.09))
            if not andando:
                ox = oy = oz = 0.0
            elif apoio:
                u = ph / prm["duty"]
                ox, oy, oz = hsx * (1 - 2 * u) + rx, hsy * (1 - 2 * u) + ry, 0.0
            else:
                u = (ph - prm["duty"]) / (1 - prm["duty"])
                sm = 0.5 * (1 - math.cos(math.pi * u))
                ox = -hsx + rx + 2 * hsx * sm
                oy = -hsy + ry + 2 * hsy * sm
                oz = prm["balanco"] * math.sin(math.pi * u) ** 2
            zc = (c_rol * np.sign(ny) - c_arf * np.sign(hx) - dz) if apoio else 0.0
            q, ok = ik_perna(ox, ny + oy - hy, -prm["altura"] + oz + zc, lado)
            if ok:
                q_des[3 * i:3 * i + 3] = q
            else:
                # alvo fora de alcance: mantem o angulo atual em vez de inventar
                self.recusados += 1
                q_des[3 * i:3 * i + 3] = d.qpos[7 + 3 * i:10 + 3 * i]

        self.tau[:] = p["kp"] * (q_des - d.qpos[7:19]) - p["kd"] * d.qvel[6:18]
        d.ctrl[:] = np.clip(self.tau, self.limites[:, 0], self.limites[:, 1])

        for _ in range(max(1, int(round(dt / m.opt.timestep)))):
            mujoco.mj_step(m, d)

        if self.caiu():
            self.quedas += 1
            ok = np.all(np.isfinite(d.qpos))
            self.reiniciar(float(d.qpos[0]) if ok else self._ini[0],
                           float(d.qpos[1]) if ok else self._ini[1],
                           yaw_de_quat(d.qpos[3:7]) if ok else self._ini[2])
            return True
        return False

    @property
    def estado(self):
        d = self.d
        return (float(d.qpos[0]), float(d.qpos[1]), float(d.qpos[2]),
                yaw_de_quat(d.qpos[3:7]))

    @property
    def vel_real(self):
        d = self.d
        psi = yaw_de_quat(d.qpos[3:7])
        c, s = math.cos(psi), math.sin(psi)
        return (c * d.qvel[0] + s * d.qvel[1], float(d.qvel[5]))
