import ips
import numpy as np
from string import ascii_uppercase, digits

sec_num = digits + ascii_uppercase


class Station:
    def __init__(self, st_obj):
        self.address = st_obj.address
        self.s_obj = st_obj
        self.connections = list()


# экстренная зарядка акб на ...мВ
Emergence_charge_acbs = 0
# экстренная разрядка акб на ...мВ
Emergence_DIScharge_acbs = 0


class MyController:
    def __init__(self, psm):
        self.psm = psm
        self.accums = ["c1"]
        self.prices = {"hA": 8, "h6": 5, "d4": 9}
        self.table = "А"

        self.obj_types = [
            "main"  # подстанции
            "miniA",  # мини-подстанции А
            "miniB",  # мини-подстанции Б
            "solar",  # солнечные электростанции
            "wind",  # ветровые электростанции
            "houseA",  # дом А
            "houseB",  # дом Б
            "factory",  # больницы
            "hospital",  # заводы
            "storage",  # накопители
        ]

        self.id2obj = dict()
        for obj in self.psm.objects:
            self.id2obj[obj.id] = obj

        self.station_names = {"main", "miniA", "miniB"}

        self.addr2obj = {obj.address[0]: obj for obj in self.psm.objects}

        self.past_tick = max(psm.tick - 1, 0)
        self.next_tick = min(psm.tick + 1, len(psm.forecasts.houseA) - 1)
        # tables ['S1c16', 'S1c15', 'S1a3', 'S1c17', 'S1c14', 'S1c13', 'S1c11']
        self.now_wind = max(psm.forecasts.wind[self.table][self.psm.tick], 0)
        self.next_wind = max(psm.forecasts.wind[self.table][self.next_tick], 0)
        self.past_sun = max(psm.forecasts.sun[self.past_tick], 0)
        self.now_sun = max(psm.forecasts.sun[self.psm.tick], 0)
        self.next_sun = max(psm.forecasts.sun[self.next_tick], 0)

        # пока не используются
        self.consumption = 0  # прогноз суммарного потребления
        self.generation = 0  # прогноз суммарной генерации

    def sun_formule(self, x, y):
        # print(x, ",", y)
        gen = np.array(x)
        sun = np.array(y)

        sun[sun < 0] = 0
        gen[sun < 0] = 0
        gen[gen < 0.1] = 0
        sun[gen < 0.1] = 0

        sun = sun[gen > 0.1]
        gen = gen[gen > 0.1]

        f0 = np.array([1] * len(gen))

        Y = sun.reshape(-1, 1)
        w = np.array([np.nan, np.nan])
        X = np.array([f0, gen]).T
        coef_matrix = np.dot(np.dot(np.linalg.inv(np.dot(X.T, X)), X.T), Y)

        b = coef_matrix.T[0][0]
        coef = coef_matrix.T[0][1]

        # рассчитаем коэффициенты используя формулу
        return coef, b

    def print_obj(self, obj):
        print("== Объект:", obj.id, "==")  # (тип, номер)
        print("Тип: ", obj.type)  # см. выше
        print("Включен:", obj.power.now.online)  # bool
        print("Тариф:", obj.contract)  # float
        print("Адрес:", obj.address)  # [str]
        print("Энергорайоны:",
              obj.path)  # [адрес энергорайона]
        print("Доход:",
              obj.score.now.income)  # float
        print("Расход:",
              obj.score.now.loss)  # float
        print("Генерация:",
              obj.power.now.generated)  # float
        print("Потребление:",
              obj.power.now.consumed)  # float
        print("Заряд (актуально для накопителя):",
              obj.charge.now)  # float

    def print_net(self, index, net):
        print("== Энергорайон", index, "==")
        print("Адрес:", net.location)
        # (ID подстанции, № линии)]
        print("Включен:", net.online)  # bool
        print("Генерация:", net.upflow)  # float
        print("Потребление:", net.downflow)  # float
        print("Потери:", net.losses)  # float
        print("Износ ветки:", net.wear)  # float

    def print_public_info(self):
        print("Ход:", self.psm.tick)  # int
        print("Всего ходов:", self.psm.gameLength)  # int
        print("Изменение счёта:", self.psm.scoreDelta)  # float
        print("Всего сгенерировано:",
              self.psm.total_power.generated)  # float
        print("Всего потреблено:",
              self.psm.total_power.consumed)  # float
        print("Получено с биржи (минус = отправлено):",
              self.psm.total_power.external)  # float
        print("Всего потерь:",
              self.psm.total_power.losses)  # float
        print("-" * 20)
        print("конец")

    def all_lines_on(self):
        for obj in self.psm.objects:
            addr = obj.address[0]
            if obj.type in self.station_names:
                # включаем линии
                for i in range(2 if obj.type == "miniB" else 3):
                    self.psm.orders.line_on(addr, i + 1)

    def objects_process(self):
        generation = 0
        consumption = 0
        for obj in self.psm.objects:
            addr = obj.address[0]
            if obj.path != (tuple(),):
                line_obj = obj.path[0][-1]
                obj_st = self.id2obj[line_obj.id].address[0]
                line_num = line_obj.line
            else:
                obj_st = None
                line_num = None

            if obj.type == "wind":
                generation += self.wind_process(obj)
                continue
            if obj.type == "solar":
                print(obj_st, line_num)
                # вычисляем прогноз солнца
                generation += self.solar_process(obj)
                continue

            # вычисляем прогноз потребления
            if obj.type.lower() == "housea":
                additional = 0.82 * (5 - self.prices[addr]) ** 2.6 if self.prices[addr] < 5 else 0
                consumption += psm.forecasts.houseA[self.next_tick] + additional + 0.5
            if obj.type.lower() == "houseb":
                additional = 0.24 * (9 - self.prices[addr]) ** 2.2 if self.prices[addr] < 8 else 0
                consumption += psm.forecasts.houseB[self.next_tick] + additional + 0.5
            if obj.type == "factory":
                consumption += psm.forecasts.factory[self.next_tick] + 0.5
            if obj.type == "hospital":
                consumption += psm.forecasts.hospital[self.next_tick] + 0.5

        shortage = abs(generation) - abs(consumption) - (
                consumption / psm.total_power.consumed) * psm.total_power.losses
        return shortage

    def wind_process(self, obj):
        # вычисляем прогноз ветра
        if obj.failed:
            self.psm.orders.line_off("e5", 1)
            return 0
        else:
            if self.now_wind <= self.next_wind:
                return obj.power.now.generated * 1.10
            else:  # now_wind > next_wind
                return obj.power.now.generated * 0.85

    def solar_process(self, obj):
        """
        Обработка солнечных панелей
        """
        line_obj = obj.path[0][-1]
        obj_st = self.id2obj[line_obj.id].address[0]
        line_num = line_obj.line
        # print("Реальность предыдущего:", obj.power.now.generated)
        corr_next_sun = max(0, self.next_sun - 0.5)
        zero_bold = 0.05
        # отключение линий с панелями ночтью для починки
        if (obj.power.then[self.past_tick].generated >= zero_bold) and (obj.power.now.generated <= zero_bold):
            self.psm.orders.line_off(obj_st, line_num)
            return 0

        self.id2obj[obj.path[0][-1].id].address
        energy = 0
        if psm.tick >= 50:
            obj_gens = [line.generated for line in obj.power.then]
            coef_, b_ = self.sun_formule(psm.sun.then, obj_gens)
            energy = self.next_sun * coef_ + b_
            # print("Параметры панели", coef_, b_)
            energy = max(min(25, energy), 0)
        else:
            if self.now_sun == 0:
                energy = 0
            else:
                energy = obj.power.now.generated * (corr_next_sun / self.now_sun)

        print([line.generated for line in obj.power.then])
        return energy

    def charge_acbs(self, energy):
        d_eng = max(min((energy / len(self.accums)), 15), 0)
        for acb in self.accums:
            self.psm.orders.charge(acb, d_eng)

    def discharge_acbs(self, energy):
        d_eng = max(min((energy / len(self.accums)), 15), 0)
        for acb in self.accums:
            psm.orders.discharge(acb, d_eng)

        self.psm.orders.humanize()

    def calc_acb(self, shortage, acb_charge, f=False):
        if (100 - acb_charge) >= 15:
            if shortage < 15:
                if f:
                    self.charge_acbs(shortage)
                return 0
            else:
                if f:
                    self.charge_acbs(15)
                return shortage - 15
        else:
            if shortage < (100 - acb_charge):
                if f:
                    self.charge_acbs(shortage)
                return 0
            else:
                if f:
                    self.charge_acbs(100 - acb_charge)
                return shortage - (100 - acb_charge)

    def calc_shortage(self, next_shortage, next_next_shortage, next_acb_charge):
        if next_shortage > 0:
            new_shortage = self.calc_acb(next_shortage, self.charger_obj.charge, f=True)
        if next_shortage < 0:
            self.discharge_acbs(abs(next_shortage))

        if next_next_shortage > 0:
            new_new_shortage = self.calc_acb(next_next_shortage, next_acb_charge)
            self.psm.orders.sell(new_new_shortage, 10)

    def close(self):
        self.psm.save_and_exit()

    def run(self):
        global Emergence_charge_acbs
        global Emergence_DIScharge_acbs

        print("Тик", self.psm.tick)
        self.all_lines_on()
        shortage = self.objects_process()
        print("SHORT", shortage)

        self.calc_shortage(next_shortage, next_next_shortage, next_acb_charge)

        # if self.psm.tick < 10:
        #     if shortage < 0:
        #         self.psm.orders.buy(abs(shortage), 1)

        # экстренная зарядка акб
        if Emergence_charge_acbs:
            self.charge_acbs(Emergence_charge_acbs)

        # экстренная разрядка акб
        if Emergence_DIScharge_acbs:
            self.discharge_acbs(Emergence_DIScharge_acbs)

        # if self.psm.tick < 10:
        #    if shortage < 0:
        #        self.psm.orders.buy(abs(shortage), 1)
        # self.charge_acbs(15) # зарядка акб
        # self.discharge_acbs(15) # разрядка акб
        # P.S. все линии каждый вход по умолчанию включаются, здесь указывайте их конечное состояние
        # self.psm.orders.line_on("e5", 1) # подключение линии (1-3)
        # self.psm.orders.line_off("e5", 1) # отключение линии (1-3)


        # self.psm.orders.sell(abs(shortage)*0.8, 10) # Заявка на продажу 10,2 МВт за 2,5 руб./МВт
        # self.psm.orders.buy(abs(shortage)*0.8, 1)# Заявка на покупку 5,5 МВт за 5,1 руб./МВт
        endpoint2obj = dict()
        for obj in self.psm.objects:
            # print(self.id2address(obj.path[0][-1].id), "asdasads")
            # print(obj.path, end=" ")
            endpoint = obj.path[-1]
            if not (endpoint in endpoint2obj.keys()):
                endpoint2obj[endpoint] = list()
            endpoint2obj[endpoint].append(obj)
            # self.print_obj(obj)

        # self.print_public_info()
        # self.topo = {tuple(self.id2obj.get(loc[0], "error") for loc in c.location): i for (i, c) in
        #             self.psm.networks.items()}
        """
        print(endpoint2obj.get(tuple())[0].path)
        for i, net in self.psm.networks.items():
            print(net.location)
            # print([self.id2obj.get(loc[0]).address for loc in net.location])
            objs = endpoint2obj.get(net.location, "error")
            if isinstance(objs, list):
                print([obj.address for obj in objs])
            else:
                print("error")
            print()
        # print(self.topo.keys())
        """
        # self.objects_process()
        print(self.psm.orders.humanize())


for i in range(2, 100):
    psm = ips.from_log("../../logs/game4.json", i)
    controller = MyController(psm)
    controller.run()
    controller  # .close()
