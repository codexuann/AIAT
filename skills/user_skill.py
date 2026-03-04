from capabilities import ui_adapter
from core import time_engine

def register(manager, skill):
    label = ui_adapter.create_label("", row=0, column=0)

    def update_time():
        current_time = time_engine.now_str()
        ui_adapter.set_label_text(label, current_time)

    update_time()
    manager.add_interval(skill.skill_id, interval_sec=1.0, callback=update_time)