import azure.functions as func
from user_info_confluent_kafka_consumer import bp_consumer
from user_info_confluent_kafka_producer import bp_producer

app = func.FunctionApp()

# 像拼图一样把逻辑组合进来
app.register_blueprint(bp_consumer)
app.register_blueprint(bp_producer)