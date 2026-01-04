import pandas as pd
import json
import random
from faker import Faker
from datetime import datetime, timedelta
import os
import uuid

fake = Faker()

def generate_test_data(num_users=100, set_num=1):
    if not os.path.exists('output'):
        os.makedirs('output')

    # --- 1. 生成基础注册用户 ---
    users_data = []
    for i in range(num_users):
        user_id = 'user' + str(set_num) + '_' + uuid.uuid4().hex[:8]
        device_id = 'device' + str(set_num) + '_'  + uuid.uuid4().hex[:8]
        mac_address = fake.mac_address()
        reg_ts = (datetime.now() - timedelta(days=random.randint(365, 730))).timestamp()
        
        users_data.append({
            "user_id": user_id,
            "device_id": device_id,
            "mac_address": mac_address,
            "registration_timestamp": reg_ts
        })
    
    df_users = pd.DataFrame(users_data)
    df_users.to_csv(f"output/1-registered_users_{set_num}.csv", index=False)

    # --- 2. 用户基础信息 (略，保持原样) ---
    user_info_list = []
    for idx, row in df_users.iterrows():
        value_content = {
            "user_id": row['user_id'],
            "dob": fake.date_of_birth(minimum_age=18, maximum_age=70).strftime('%Y-%m-%d'),
            "sex": random.choice(['M', 'F']),
            "gender": random.choice(['Male', 'Female', 'Non-binary']),
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "address": {"street_address": fake.street_address(), "city": fake.city(), "state": fake.state_abbr(), "zip": int(fake.zipcode())},
            "timestamp": str(datetime.now()),
            "update_type": "new"
        }
        user_info_list.append(json.dumps(value_content))
    with open(f"output/2-user_info_{set_num}.json", 'w') as f:
        json.dump(user_info_list, f, indent=4)

    # --- 核心修改部分：关联逻辑 ---
    
    gym_logins = []
    workout_list = []
    bpm_list = []
    
    # 遍历用户，模拟具有关联性的行为
    for idx, row in df_users.iterrows():
        # 假设 70% 的用户有活动数据
        if random.random() > 0.7:
            continue
            
        # A. 生成 Gym Login (顶层时间)
        # 模拟发生在过去 24 小时内的一次健身房访问
        base_time = datetime.now() - timedelta(hours=random.randint(2, 24))
        login_dt = base_time
        duration_minutes = random.randint(45, 120) # 健身 45-120 分钟
        logout_dt = login_dt + timedelta(minutes=duration_minutes)
        
        gym_logins.append({
            "mac_address": row['mac_address'],
            "gym": random.randint(101, 110),
            "login": int(login_dt.timestamp()),
            "logout": int(logout_dt.timestamp())
        })
        
        # B. 生成 Workout (在登录期间内)
        # 运动在进入健身房 5 分钟后开始
        workout_start_dt = login_dt + timedelta(minutes=5)
        # 运动在离开前 5 分钟结束
        workout_stop_dt = logout_dt - timedelta(minutes=5)
        
        session_id = "session" + str(set_num) + '_' + uuid.uuid4().hex[:8]
        workout_id = "workout_id" + str(set_num) + '_'  + uuid.uuid4().hex[:8]
        # 写入 Start 记录
        for action, action_dt in [("start", workout_start_dt), ("stop", workout_stop_dt)]:
            val_workout = {
                "user_id": row['user_id'],
                "workout_id": workout_id,
                "time": action_dt.strftime('%Y-%m-%d %H:%M:%S'),
                "action": action,
                "session_id": session_id
            }
            workout_list.append(json.dumps(val_workout))

        # C. 生成 BPM (在运动期间内)
        # 在运动期间生成 3 条心率快照
        for i in range(3):
            # 随机在运动开始和结束之间取一个点
            offset_sec = random.randint(60, int((workout_stop_dt - workout_start_dt).total_seconds()) - 60)
            bpm_dt = workout_start_dt + timedelta(seconds=offset_sec)
            
            val_bpm = {
                "device_id": row['device_id'],
                "time": bpm_dt.strftime('%Y-%m-%d %H:%M:%S'),
                "heartrate": round(random.uniform(100.0, 160.0), 2) # 运动时心率较高
            }
            bpm_list.append(json.dumps(val_bpm))

    # --- 写入文件 ---
    with open(f"output/3-bpm_{set_num}.json", 'w') as f:
        json.dump(bpm_list, f, indent=4)
        
    with open(f"output/4-workout_{set_num}.json", 'w') as f:
        json.dump(workout_list, f, indent=4)
        
    pd.DataFrame(gym_logins).to_csv(f"output/5-gym_logins_{set_num}.csv", index=False)
    
    print(f"Set {set_num} 数据关联生成完毕！")

if __name__ == "__main__":
    generate_test_data(num_users=100, set_num=5)