
删除
```
uv run python run.py \
  --delete-dataset medical-safety-review-test \
  --yes
```

查询
```
uv run python run.py --mode review --dry-run
```

创建
```
uv run python run.py \
  --mode review \
  --offset 20 \
  --limit 10 \
  --random \
  --min-submitted 1 \
  --input 'workbench/input/safety_classifier_results_340_annotation_ready.csv' \
  --dataset medical-safety-review-test
```

细节创建
```
uv run python run.py \
  --mode review \
  --offset 20 \
  --limit 10 \
  --random \
  --min-submitted 5 \
  --input 'workbench/input/safety_classifier_results_340_annotation_ready.csv' \
  --dataset medical-annotation-5p-limit10
```

查看数据进度
```
uv run python run.py \
  --progress-dataset product-safety-review-v2-2p-full340
```

导出
```
uv run python run.py \
  --export-dataset product-safety-review-smoke-1p-limit20
```

创建用户
```
uv run python run.py \
  --create-users 10 \
  --user-prefix prod_reviewer
```

删除用户
```
uv run python run.py \
  --delete-users 10 \
  --user-prefix medical_reviewer
```


```
登录：http://172.17.23.51:6900
账号密码找我私
```
